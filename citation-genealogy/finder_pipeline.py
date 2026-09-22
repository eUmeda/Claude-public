#!/usr/bin/env python3
"""見落とし候補の分類パイプライン（v0.3.1・標準ライブラリのみ）

build_finder.py から呼ぶ。同じ関数を holdout 評価（既知の一部を隠して当てられるか）にも使う。

手順:
  merge_aliases   同一論文の別レコード（DOI 一致、または正規化タイトル＋年が一致）を 1 件に統合
  topology        既知文献 k ごとのつながりの強さ s(w,k) を 3 チャネルから合成
                    D  直接引用（どちら向きでも）                      s_D  = 1
                    CC 共引用: k の引用者のうち w も引用する割合 frac   s_CC = 1 - exp(-frac/FRAC)  (cc>=3, frac>=1%)
                    BC 参照共有: |refs(w)∩refs(k)| のコサイン bcos       s_BC = 1 - exp(-bcos/BCOS)  (bc>=3)
                  s = 1 − (1−s_D)(1−s_CC)(1−s_BC)。S_topo = Σ_k s（既知とのつながりの期待数）。
                  N_link = 「確かな」つながりの本数（直接 / cc>=3 かつ frac>=1.5% / bc>=3 かつ bcos>=0.04）
  semantic        TF-IDF コサイン（タイトル＋要旨）。最近傍の既知、共通語幹、クラスタ重心との類似度
  classify        tier: 1 要確認（直接 2 件以上）/ 2 関連（N_link >= 2）/ 3 意味ベースの保険 / 5 既知の別版 / 0 海
  holdout         既知 = phase <= N だけにして残りを隠し、隠した文献がどの tier・順位に来るかを測る
"""
import math
import re
from collections import Counter, defaultdict

from finder_signals import TfIdf, short, tokens

CONFIG = dict(
    FRAC=0.03, BCOS=0.10,              # 飽和定数（この値で s = 0.63、3 倍で 0.95。軟飽和）
    CC_MIN=3, FRAC_MIN=0.01,           # 共引用チャネルの下限
    CC_SOLID_FRAC=0.015,               # 「確かな」共引用: cc>=CC_MIN かつ frac>=これ
    BC_MIN=3, BC_SOLID_COS=0.04,       # 参照共有チャネルの下限 / 確かな共有
    GENERIC_NW=100, GENERIC_LIFT=2.5,  # 汎用文献（統計教科書など）の目印
    THETA_FLOOR=0.22, THETA_T_FLOOR=0.30, BG_PCT=0.97,
    SEM_SHARED_MIN=3, SEM_CAP=300, SEM_CAP_CLUSTER=60, SEM_CAP_KNOWN=40,
    DUP_COS=0.8, DUP_DY=1,
)
TITLE_NORM_RE = re.compile(r"[^a-z0-9]+")


def norm_doi(d):
    if not d:
        return None
    return d.lower().replace("https://doi.org/", "").strip() or None


def norm_title(t):
    return TITLE_NORM_RE.sub("", (t or "").lower())[:120]


def first_author_surname(w):
    a = (w.get("authorships") or [{}])[0].get("author", {}).get("display_name") or ""
    return a.split()[-1].lower() if a else ""


# ---------------------------------------------------------------- 別名統合
def merge_aliases(works, protected):
    """works: {id: record}。DOI または（タイトル＋年）が一致するレコードを統合する。
    protected（既知）は必ず正規レコードにする。返り値: (統合後 works, {alias_id: canonical_id}, merged_pairs)"""
    by_doi, by_title = {}, {}
    alias = {}
    order = sorted(works, key=lambda i: (0 if i in protected else 1, -(works[i].get("cited_by_count") or 0)))
    for wid in order:
        w = works[wid]
        d = norm_doi(w.get("doi"))
        t = norm_title(w.get("title"))
        y = w.get("publication_year")
        canon = None
        if d and d in by_doi:
            canon = by_doi[d]
        elif t and len(t) >= 20 and (t, y) in by_title:
            canon = by_title[(t, y)]
        if canon and canon != wid and wid not in protected:
            alias[wid] = canon
            continue
        if d:
            by_doi.setdefault(d, wid)
        if t and len(t) >= 20:
            by_title.setdefault((t, y), wid)
    merged = []
    out = {}
    for wid, w in works.items():
        if wid in alias:
            c = alias[wid]
            # 参照リストは和集合、被引用数は大きい方
            cw = works[c]
            refs = set(short(r) for r in cw.get("referenced_works") or []) | set(short(r) for r in w.get("referenced_works") or [])
            cw["referenced_works"] = ["https://openalex.org/" + r for r in sorted(refs)]
            cw["cited_by_count"] = max(cw.get("cited_by_count") or 0, w.get("cited_by_count") or 0)
            if not cw.get("abstract") and w.get("abstract"):
                cw["abstract"] = w["abstract"]
            merged.append([wid, c, (w.get("title") or "")[:80]])
        else:
            out[wid] = w
    # 参照リスト内の別名 ID を正規 ID へ
    for w in out.values():
        if w.get("referenced_works"):
            seen, refs = set(), []
            for r in w["referenced_works"]:
                rs = alias.get(short(r), short(r))
                if rs not in seen:
                    seen.add(rs)
                    refs.append("https://openalex.org/" + rs)
            w["referenced_works"] = refs
    return out, alias, merged


# ---------------------------------------------------------------- 位相
def topology(works, known_ids, cfg=CONFIG):
    """返り値: {w: {"S": S_topo, "N": N_link, "ev": [[k, bits, s, cc, frac, bc], ...], "direct": set(k), "nw": n_w, "generic": bool}}"""
    K = list(known_ids)
    Kset = set(K)
    refs = {wid: {short(r) for r in w.get("referenced_works") or []} for wid, w in works.items()}
    # 引用者集合 C（既知を引用する非既知）
    C = [w for w in works if w not in Kset and refs[w] & Kset]
    n_k = Counter()
    for c in C:
        for k in refs[c] & Kset:
            n_k[k] += 1
    n_w = Counter()
    cc = defaultdict(Counter)   # w -> {k: count}
    for c in C:
        ks = refs[c] & Kset
        for r in refs[c]:
            if r in Kset or r not in works:
                continue
            n_w[r] += 1
            for k in ks:
                cc[r][k] += 1
    # 参照共有（既知の参照 → 既知）
    ref_to_k = defaultdict(set)
    for k in K:
        for r in refs.get(k, ()):
            ref_to_k[r].add(k)
    nC = max(1, len(C))
    out = {}
    for w in works:
        if w in Kset:
            continue
        rw = refs[w]
        direct = set()
        for k in K:
            if k in rw or w in refs.get(k, ()):
                direct.add(k)
        bc = Counter()
        for r in rw:
            for k in ref_to_k.get(r, ()):
                if k != w:
                    bc[k] += 1
        S, N, ev = 0.0, 0, []
        max_lift = 0.0
        ks = direct | set(cc[w]) | set(bc)
        for k in ks:
            sD = 1.0 if k in direct else 0.0
            c = cc[w].get(k, 0)
            frac = c / n_k[k] if n_k[k] else 0.0
            lift = frac / (n_w[w] / nC) if n_w[w] else 0.0
            max_lift = max(max_lift, lift)
            sCC = (1.0 - math.exp(-frac / cfg["FRAC"])) if (c >= cfg["CC_MIN"] and frac >= cfg["FRAC_MIN"]) else 0.0
            b = bc.get(k, 0)
            bcos = b / math.sqrt(len(rw) * len(refs[k])) if (rw and refs[k]) else 0.0
            sBC = (1.0 - math.exp(-bcos / cfg["BCOS"])) if b >= cfg["BC_MIN"] else 0.0
            s = 1 - (1 - sD) * (1 - sCC) * (1 - sBC)
            if s <= 0:
                continue
            solid = sD > 0 or (c >= cfg["CC_MIN"] and frac >= cfg["CC_SOLID_FRAC"]) or (b >= cfg["BC_MIN"] and bcos >= cfg["BC_SOLID_COS"])
            bits = (1 if k in rw else 0) | (2 if w in refs.get(k, ()) else 0) | (4 if sCC > 0 else 0) | (8 if sBC > 0 else 0) | (0 if solid else 32)
            S += s
            N += 1 if solid else 0
            ev.append([k, bits, round(s, 3), c, round(frac, 4), b])
        ev.sort(key=lambda e: -e[2])
        generic = n_w[w] >= cfg["GENERIC_NW"] and (max_lift < cfg["GENERIC_LIFT"] or (len(K) >= 20 and N >= 0.5 * len(K)))
        out[w] = {"S": round(S, 3), "N": N, "ev": ev[:12], "direct": direct, "nw": n_w[w], "generic": generic}
    return out, {"n_citers": len(C), "n_k": dict(n_k)}


# ---------------------------------------------------------------- 意味
def semantic(works, known_ids, known_cluster, topo, cfg=CONFIG):
    """TF-IDF コサイン。返り値 {w: {"sim","nn","kt","simc","cluster"}} と θ 情報"""
    docs = {wid: (w.get("title") or "", w.get("abstract") or "") for wid, w in works.items()}
    tf = TfIdf(docs)
    Kset = set(known_ids)
    seed_vecs = {k: tf.vec[k] for k in known_ids if k in tf.vec}
    by_cluster = defaultdict(list)
    for k, v in seed_vecs.items():
        by_cluster[known_cluster[k]].append(v)
    # クラスタ重心（既知＋位相で確かにつながる上位 100 件で拡張）
    ext = defaultdict(list)
    ranked = sorted((w for w in topo if topo[w]["N"] >= 2), key=lambda w: -topo[w]["S"])
    for w in ranked:
        cnt = Counter(known_cluster[e[0]] for e in topo[w]["ev"] if not (e[1] & 32))
        if cnt:
            c = cnt.most_common(1)[0][0]
            if len(ext[c]) < 100 and w in tf.vec:
                ext[c].append(tf.vec[w])
    cent = {c: TfIdf.centroid(vs + ext.get(c, [])) for c, vs in by_cluster.items()}
    out = {}
    for wid, v in tf.vec.items():
        if wid in Kset:
            continue
        best, nn = 0.0, None
        for k, sv in sorted(seed_vecs.items()):      # 順序を固定して同点時の結果を決定的にする
            d = TfIdf.dot(v, sv)
            if d > best:
                best, nn = d, k
        bc, bcl = 0.0, None
        for c, cv in sorted(cent.items()):
            d = TfIdf.dot(v, cv)
            if d > bc:
                bc, bcl = d, c
        kt = []
        if nn:
            shared = set(v) & set(seed_vecs[nn])
            kt = sorted(shared, key=lambda t: -v[t])[:4]
        out[wid] = {"sim": round(best, 3), "nn": nn, "kt": kt, "simc": round(bc, 3), "cluster": bcl}
    # 背景分布から θ
    has_ab = lambda w: bool(works[w].get("abstract"))
    bg = sorted(out[w]["sim"] for w in out if topo.get(w, {}).get("N", 0) <= 1 and has_ab(w))
    bg_t = sorted(out[w]["sim"] for w in out if topo.get(w, {}).get("N", 0) <= 1 and not has_ab(w))
    pct = lambda arr, p: arr[min(len(arr) - 1, int(len(arr) * p))] if arr else 0.0
    theta = max(cfg["THETA_FLOOR"], pct(bg, cfg["BG_PCT"]))
    theta_t = max(cfg["THETA_T_FLOOR"], pct(bg_t, cfg["BG_PCT"]))
    info = {"theta": round(theta, 3), "theta_noabs": round(theta_t, 3),
            "bg_p50": round(pct(bg, 0.5), 3), "bg_p90": round(pct(bg, 0.9), 3), "bg_p99": round(pct(bg, 0.99), 3)}
    return out, info


# ---------------------------------------------------------------- 分類
def classify(works, known_ids, known_cluster, related_ids, topo, sem, seminfo, cfg=CONFIG):
    """返り値 {w: {"tier", "score", "dup"}}。tier: 1 要確認 / 2 関連 / 3 意味 / 5 既知の別版 / 0 海"""
    Kset = set(known_ids)
    p50, p99 = seminfo["bg_p50"], max(seminfo["bg_p99"], seminfo["bg_p50"] + 1e-6)
    res = {}
    sem_pool = []
    for w in works:
        if w in Kset:
            continue
        t = topo.get(w, {"S": 0.0, "N": 0, "direct": set(), "generic": False})
        s = sem.get(w, {"sim": 0.0, "nn": None, "kt": [], "cluster": None})
        score = t["S"] + max(0.0, min(1.0, (s["sim"] - p50) / (p99 - p50)))
        dup = False
        if s["nn"] and s["sim"] >= cfg["DUP_COS"]:
            y1, y2 = works[w].get("publication_year"), works[s["nn"]].get("publication_year")
            if y1 and y2 and abs(y1 - y2) <= cfg["DUP_DY"] and first_author_surname(works[w]) == first_author_surname(works[s["nn"]]):
                dup = True
        if dup:
            tier = 5
        elif len(t["direct"]) >= 2:
            tier = 1
        elif t["N"] >= 2:
            tier = 2
        else:
            tier = 0
            has_ab = bool(works[w].get("abstract"))
            theta = seminfo["theta"] if has_ab else seminfo["theta_noabs"]
            if (s["sim"] >= theta and len(s["kt"]) >= cfg["SEM_SHARED_MIN"]) or (w in related_ids and s["sim"] >= seminfo["bg_p90"]):
                sem_pool.append(w)
        res[w] = {"tier": tier, "score": round(score, 3), "dup": dup}
    # 意味ベースの保険: 上限（全体・クラスタ・最近傍ごと）
    sem_pool.sort(key=lambda w: -sem[w]["sim"])
    per_c, per_k, n = Counter(), Counter(), 0
    for w in sem_pool:
        c, k = sem[w]["cluster"], sem[w]["nn"]
        if n >= cfg["SEM_CAP"] or per_c[c] >= cfg["SEM_CAP_CLUSTER"] or per_k[k] >= cfg["SEM_CAP_KNOWN"]:
            continue
        res[w]["tier"] = 3
        per_c[c] += 1; per_k[k] += 1; n += 1
    return res


# ---------------------------------------------------------------- 一括実行
def run(works, known_ids, known_cluster, related_ids, cfg=CONFIG):
    topo, tinfo = topology(works, known_ids, cfg)
    sem, seminfo = semantic(works, known_ids, known_cluster, topo, cfg)
    res = classify(works, known_ids, known_cluster, related_ids, topo, sem, seminfo, cfg)
    return topo, sem, res, {"topology": tinfo, "semantic": seminfo}


def holdout(works_all, seeds_by_id, related_ids, phase_max, cfg=CONFIG):
    """既知 = phase <= phase_max のみ。プール = その参照 ∪ 引用者 ∪（引用者の参照で取得済みのもの）∪ 隠した既知。
    隠した既知がどこに来るかを返す。"""
    known = [i for i, s in seeds_by_id.items() if s["phase"] <= phase_max]
    hidden = [i for i in seeds_by_id if i not in known]
    Kset = set(known)
    refs = {wid: {short(r) for r in w.get("referenced_works") or []} for wid, w in works_all.items()}
    pool = set(known)
    for k in known:
        pool |= {r for r in refs[k] if r in works_all}
    citers = [w for w in works_all if w not in Kset and refs[w] & Kset]
    pool |= set(citers)
    for c in citers:
        pool |= {r for r in refs[c] if r in works_all}
    pool |= set(hidden)
    sub = {w: works_all[w] for w in pool}
    kc = {k: seeds_by_id[k]["cluster"] for k in known}
    topo, sem, res, info = run(sub, known, kc, related_ids, cfg)
    ranked = sorted((w for w in res), key=lambda w: (-res[w]["score"]))
    rank = {w: i + 1 for i, w in enumerate(ranked)}
    rows = []
    for h in hidden:
        r = res.get(h)
        t = topo.get(h, {})
        rows.append({"key": seeds_by_id[h]["key"], "tier": r["tier"] if r else None, "rank": rank.get(h),
                     "N": t.get("N", 0), "direct": len(t.get("direct", ())), "S": t.get("S", 0.0),
                     "sim": sem.get(h, {}).get("sim", 0.0), "nn": seeds_by_id.get(sem.get(h, {}).get("nn"), {}).get("key"),
                     "in_pool": h in sub, "pool_links": t.get("nw", 0)})
    recall = {f"top{n}": sum(1 for r in rows if r["rank"] and r["rank"] <= n) for n in (100, 500, 1000)}
    tiers = Counter(r["tier"] for r in rows)
    return {"phase_max": phase_max, "known": len(known), "hidden": len(hidden), "pool": len(sub), "rows": rows,
            "recall": recall, "tiers": {str(k): v for k, v in tiers.items()}, "info": info}
