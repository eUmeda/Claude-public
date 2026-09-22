#!/usr/bin/env python3
"""見落とし検出ビューア（v0.3）のデータ整形・ページ生成

入力: data/known_list.csv と fetch_crawl.py の出力 data/crawl/*.json
出力:
  - data/finder.json   整形済み（ノード・辺・索引・レイアウト・統計）
  - index.html         finder.html にデータを埋め込んだ自己完結ページ（GitHub Pages 用）
  - artifact.html      claude.ai Artifact 用フラグメント

候補の階層（tier）:
  1 要確認        既知リストの 2 件以上と直接の引用関係（引用 or 被引用）
  2 関連の可能性  直接 1 件 かつ（共引用の既知種類数 >= 8 / 既知 1 件と参照を 8 本以上共有 /
                  類似度 >= 0.30）、または直接 0 件だが共引用の既知種類数 >= 12（共引用候補として本体取得済み）
  3 意味ベースの保険  上記に該当せず、TF-IDF コサインが閾値以上、または OpenAlex の related_works
  0 海            既知 1 件だけとつながる文献（背景として位置だけ描く）
"""
import base64
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from finder_signals import (TfIdf, bibliographic_coupling, direct_links, semantic_scores,
                            short, stem, tokens, topic_match)

HERE = Path(__file__).parent
CRAWL = HERE / "data" / "crawl"
CLUSTER_ORDER = ["nlm", "field", "light", "ms", "forest", "evo", "stat", "lai"]
CLUSTER_LABEL = {
    "nlm": "中立景観モデル", "field": "確率場・空間統計", "light": "林床光環境", "ms": "群落光合成（Monsi–Saeki）",
    "forest": "森林動態", "evo": "分散・進化", "stat": "空間統計（生態）", "lai": "LAI・葉群計測",
}
SEM_THRESHOLD = 0.32     # T3: TF-IDF コサインの保険閾値（直接接続なしでも拾う）
T2_COCITE = 8            # T2: 直接 1 件 かつ 共引用の既知種類数
T2_COUPLING_BEST = 8     # T2: 直接 1 件 かつ 既知 1 件と共有する参照数
T2_SIM = 0.30            # T2: 直接 1 件 かつ 類似度
T2_COCITE_ONLY = 12      # T2: 直接 0 件 かつ 共引用の既知種類数
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def clean(t, limit=None):
    if not t:
        return None
    t = WS_RE.sub(" ", TAG_RE.sub("", t)).strip()
    if limit and len(t) > limit:
        t = t[:limit - 1] + "…"
    return t or None


def hash01(s):
    h = 2166136261
    for ch in s:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return (h % 10000) / 10000


def authors_of(w, keep=3):
    names = [a.get("author", {}).get("display_name") for a in (w.get("authorships") or [])]
    names = [n for n in names if n]
    if not names:
        return None
    return ", ".join(names[:keep]) + (f" ほか{len(names) - keep}名" if len(names) > keep else "")


def venue_of(w):
    loc = w.get("primary_location") or {}
    src = loc.get("source") or {}
    return clean(src.get("display_name") or loc.get("raw_source_name"), 60)


def load(name, default):
    p = CRAWL / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def varint(values):
    b = bytearray()
    for v in values:
        while v >= 0x80:
            b.append((v & 0x7F) | 0x80)
            v >>= 7
        b.append(v)
    return bytes(b)


def build_keyword_index(docs):
    """docs: list of (node_index, text). 語 → ノード添字リスト（デルタ varint, base64）"""
    postings = defaultdict(list)
    n_docs = 0
    for i, text in docs:
        if not text:
            continue
        n_docs += 1
        for t in set(tokens(text)):
            postings[t].append(i)
    max_df = max(2, int(0.25 * max(1, n_docs)))
    vocab = sorted(t for t, lst in postings.items() if 2 <= len(lst) <= max_df)
    blob, offsets, total = bytearray(), [], 0
    for t in vocab:
        lst = postings[t]
        offsets.append(len(blob))
        prev, deltas = -1, []
        for i in lst:
            deltas.append(i - prev - 1)
            prev = i
        blob += varint([len(lst)] + deltas)
        total += len(lst)
    offsets.append(len(blob))
    return ({"vocab": vocab, "off": offsets, "blob": base64.b64encode(bytes(blob)).decode("ascii")},
            {"docs": n_docs, "terms": len(vocab), "postings": total, "blob_kb": len(blob) * 4 // 3 // 1024})


def main():
    seeds = load("seeds.json", {})
    if not seeds:
        sys.exit("data/crawl/seeds.json がありません。先に fetch_crawl.py を実行してください。")
    status = load("status.json", {})
    cocite_stats = load("cocite_stats.json", {})
    related_ids = {short(r) for s in seeds.values() for r in s.get("related_works") or []}

    # ---- works 表（id → record）と層 ----------------------------------------
    works, layer = {}, {}
    for key, s in seeds.items():
        wid = short(s["id"])
        works[wid] = s
        layer[wid] = "known"
    for name, lay in (("refs.json", "ref"), ("citers.json", "citer"), ("cocited.json", "cocited"), ("related.json", "related")):
        for w in load(name, []):
            wid = short(w["id"])
            if wid not in works:
                works[wid] = w
                layer[wid] = lay
    seed_key = {short(s["id"]): k for k, s in seeds.items()}
    seed_ids = list(seed_key)
    seed_cluster = {sid: seeds[k]["cluster"] for sid, k in seed_key.items()}
    seed_index = {sid: i for i, sid in enumerate(seed_ids)}
    print(f"works: {len(works)}  layers: {Counter(layer.values())}")

    # ---- 信号 ----------------------------------------------------------------
    links = direct_links(works, seed_ids)
    coupling = bibliographic_coupling(works, seed_ids)
    topic_ok, seed_topics = topic_match(works, seed_ids)
    docs = {wid: (w.get("title") or "", w.get("abstract") or "") for wid, w in works.items()}
    tfidf = TfIdf(docs)
    sem = semantic_scores(tfidf, seed_ids, seed_cluster)
    del tfidf
    print("signals computed")

    # ---- 候補階層とスコア ------------------------------------------------------
    def distinct_direct(wid):
        L = links.get(wid)
        if not L:
            return set()
        return set(L["cites"]) | set(L["cited_by"])

    tiers, scores = {}, {}
    for wid in works:
        if wid in seed_key:
            tiers[wid] = -1
            scores[wid] = 0
            continue
        dd = distinct_direct(wid)
        nd = len(dd)
        cc = cocite_stats.get(wid, [0, 0])
        cp = coupling.get(wid, {}).get("coupling", 0)
        cpb = coupling.get(wid, {}).get("coupling_best", 0)
        sm = sem.get(wid, {}).get("sim_seed", 0.0)
        tm = topic_ok.get(wid, False)
        rl = wid in related_ids
        if nd >= 2:
            tier = 1
        elif nd == 1 and (cc[1] >= T2_COCITE or cpb >= T2_COUPLING_BEST or sm >= T2_SIM):
            tier = 2
        elif nd == 0 and cc[1] >= T2_COCITE_ONLY:
            tier = 2
        elif sm >= SEM_THRESHOLD or rl:
            tier = 3
        else:
            tier = 0
        tiers[wid] = tier
        c = works[wid].get("cited_by_count") or 0
        scores[wid] = round(3 * nd + 1.5 * math.log1p(cc[1]) + 1.0 * math.log1p(cp) + 4 * sm + (1 if tm else 0) + (1 if rl else 0) + 0.5 * math.log10(c + 1), 2)
    tier_counts = Counter(tiers.values())
    print(f"tiers: known={tier_counts[-1]} T1={tier_counts[1]} T2={tier_counts[2]} T3={tier_counts[3]} sea={tier_counts[0]}")
    sims = sorted((sem[w]["sim_seed"] for w in works if tiers[w] in (0, 3)), reverse=True)
    if sims:
        print(f"sim_seed among non-candidates: p50={sims[len(sims)//2]:.3f} p90={sims[len(sims)//10]:.3f} p98={sims[len(sims)//50]:.3f} max={sims[0]:.3f}")

    # ---- クラスタ割当（色と横位置） ---------------------------------------------
    cluster_of = {}
    for wid in works:
        if wid in seed_key:
            cluster_of[wid] = seed_cluster[wid]
            continue
        cnt = Counter(seed_cluster[s] for s in distinct_direct(wid))
        if cnt:
            top = max(cnt.values())
            cands = [c for c in CLUSTER_ORDER if cnt.get(c) == top]
            cluster_of[wid] = cands[0]
        else:
            cluster_of[wid] = sem.get(wid, {}).get("sim_cluster_name") or CLUSTER_ORDER[0]

    # ---- 辺（取得済み集合内の参照関係。既知 or 候補に触れるものだけ埋め込む） ------------
    ids = list(works)
    index = {wid: i for i, wid in enumerate(ids)}
    in_deg = Counter()
    edges = []
    for wid, w in works.items():
        for r in w.get("referenced_works") or []:
            rs = short(r)
            if rs in works and rs != wid:
                in_deg[rs] += 1
                # 埋め込む辺: どちらかが既知、または両方が候補（海→候補の大量の辺は件数 ind にだけ反映）
                if tiers[wid] == -1 or tiers[rs] == -1 or (tiers[wid] > 0 and tiers[rs] > 0):
                    edges.append((index[wid], index[rs]))
    edges = sorted(set(edges))
    print(f"edges embedded: {len(edges)}  (in-set citations total: {sum(in_deg.values())})")

    # ---- ノード ------------------------------------------------------------------
    nodes = []
    for wid in ids:
        w = works[wid]
        tier = tiers[wid]
        year = w.get("publication_year")
        is_known = wid in seed_key
        L = links.get(wid, {"cites": [], "cited_by": []})
        node = {
            "id": wid, "t": clean(w.get("title"), 140 if tier != 0 else 90) or "(no title)",
            "y": year, "c": w.get("cited_by_count"), "cl": cluster_of[wid], "tier": tier,
            "ind": in_deg.get(wid, 0),
            "dc": sorted({seed_index[s] for s in L["cites"]}),      # 引用している既知文献（添字）
            "db": sorted({seed_index[s] for s in L["cited_by"]}),   # この文献を引用している既知文献
        }
        if tier != 0:
            cc = cocite_stats.get(wid, [0, 0])
            cp = coupling.get(wid, {})
            sm = sem.get(wid, {})
            node.update({
                "doi": (w.get("doi") or "").replace("https://doi.org/", "") or None,
                "au": authors_of(w, 3 if tier in (-1, 1) else 2), "v": venue_of(w), "tp": clean((w.get("primary_topic") or {}).get("display_name"), 60),
                "ly": layer[wid], "sc": scores[wid],
                "cc": cc, "cp": cp.get("coupling", 0), "cpb": cp.get("coupling_best", 0),
                "cpbi": seed_index.get(cp.get("coupling_best_id")) if cp.get("coupling_best_id") in seed_index else None,
                "ss": sm.get("sim_seed", 0), "ssi": seed_index.get(sm.get("sim_seed_id")) if sm.get("sim_seed_id") in seed_index else None,
                "scl": sm.get("sim_cluster", 0), "scn": sm.get("sim_cluster_name"),
                "tm": topic_ok.get(wid, False), "rl": wid in related_ids,
                "nref": len(w.get("referenced_works") or []), "hasAb": bool(w.get("abstract")),
            })
        if is_known:
            s = w
            node.update({"key": s["key"], "cluster": s["cluster"], "phase": s["phase"], "note": s["note"],
                         "ab": clean(s.get("abstract"), 1500), "ki": seed_index[wid]})
        nodes.append(node)

    # ---- レイアウト ------------------------------------------------------------
    W, YPX = 6000.0, 40.0
    PAD_TOP, PAD_BOTTOM = 80, 100
    years = [n["y"] for n in nodes if n["y"]]
    known_years = [n["y"] for n in nodes if n["tier"] == -1 and n["y"]]
    # 年の下限: 既知の最古 − 20 年。それより古い文献（数件）は最下段の帯にまとめる
    floor_year = max(min(years), min(known_years) - 20)
    max_year, min_year = max(years) + 1, floor_year - 1
    H = PAD_TOP + (max_year - min_year) * YPX + PAD_BOTTOM
    NOYEAR_Y = H - PAD_BOTTOM / 2
    y_of = lambda yr: PAD_TOP + (max_year - max(yr, floor_year)) * YPX
    older = sum(1 for y in years if y < floor_year)
    print(f"year floor {floor_year} (older works folded into the bottom band: {older})")
    home = {c: W * (0.06 + 0.88 * i / (len(CLUSTER_ORDER) - 1)) for i, c in enumerate(CLUSTER_ORDER)}
    ROWS = 8   # 1年帯（40px）を 8 列に分ける

    def radius(n):
        if n["tier"] == -1:
            return 9.0
        if n["tier"] == 1:
            return 4.2 + min(2.5, 0.5 * math.log1p(n["ind"]))
        if n["tier"] in (2, 3):
            return 3.4 + min(2.0, 0.4 * math.log1p(n["ind"]))
        return 1.8

    for n in nodes:
        n["r"] = round(radius(n), 2)
        base = home[n["cl"]]
        spread = 0.045 if n["tier"] == -1 else 0.055 if n["tier"] == 1 else 0.07
        n["x"] = base + (hash01(n["id"]) - 0.5) * 2 * spread * W
        row = 0 if n["tier"] == -1 else int(hash01(n["id"] + "row") * ROWS)
        n["_row"] = row
        by = y_of(n["y"]) if n["y"] else NOYEAR_Y
        n["yy"] = by if n["tier"] == -1 else by - YPX / 2 + (row + 0.5) * (YPX / ROWS)
    # 既知文献は同じクラスタ内で phase 順に少し横へずらす（重なり防止）
    bands = defaultdict(list)
    for n in nodes:
        bands[(n["y"] or 0, n["_row"])].append(n)
    GAP = 1.2
    for band in bands.values():
        if len(band) < 2:
            continue
        for _ in range(80):
            band.sort(key=lambda m: m["x"])
            moved = False
            for a, b in zip(band, band[1:]):
                need = a["r"] + b["r"] + GAP
                d = b["x"] - a["x"]
                if d < need:
                    push = (need - d) / 2
                    a["x"] -= push
                    b["x"] += push
                    moved = True
            if not moved:
                break
        lo = min(m["x"] - m["r"] for m in band)
        hi = max(m["x"] + m["r"] for m in band)
        shift = 30 - lo if lo < 30 else (W - 30) - hi if hi > W - 30 else 0.0
        for m in band:
            m["x"] = round(min(W - 30, max(30, m["x"] + shift)), 1)
    for n in nodes:
        n["x"] = round(n["x"], 1)
        n["yy"] = round(n["yy"], 1)
        n.pop("_row", None)

    # ---- 密度（俯瞰用: 年 × クラスタ の件数） ---------------------------------------
    density = defaultdict(lambda: [0] * len(CLUSTER_ORDER))
    ci = {c: i for i, c in enumerate(CLUSTER_ORDER)}
    for n in nodes:
        if n["y"]:
            density[max(n["y"], floor_year)][ci[n["cl"]]] += 1
    density = {str(y): v for y, v in sorted(density.items())}

    # ---- 索引（要旨＋タイトル。候補以外は本文を埋め込まないため索引で検索する） -----------
    kw, kw_stats = build_keyword_index([(i, (works[n["id"]].get("title") or "") + " " + (works[n["id"]].get("abstract") or "")) for i, n in enumerate(nodes)])
    print(f"keyword index: {kw_stats}")

    # ---- meta -----------------------------------------------------------------
    known_rows = [{"i": seed_index[sid], "key": seed_key[sid], "cluster": seed_cluster[sid], "phase": seeds[seed_key[sid]]["phase"],
                   "note": seeds[seed_key[sid]]["note"], "year": works[sid].get("publication_year"),
                   "cited": works[sid].get("cited_by_count"), "refs": len(works[sid].get("referenced_works") or []),
                   "citers": (status.get("seeds", {}).get(seed_key[sid], {}) or {}).get("citers"),
                   "node": index[sid]} for sid in seed_ids]
    meta = {
        "version": "0.3", "generated": "2026-09-22", "source": "OpenAlex (2026-09-22 取得)",
        "clusters": CLUSTER_ORDER, "clusterLabel": CLUSTER_LABEL, "known": known_rows,
        "counts": {"nodes": len(nodes), "edges": len(edges), "known": tier_counts[-1], "t1": tier_counts[1],
                   "t2": tier_counts[2], "t3": tier_counts[3], "sea": tier_counts[0],
                   "max_cited": max((n["c"] or 0) for n in nodes), "max_ind": max(n["ind"] for n in nodes)},
        "coverage": {"refs": status.get("refs"), "cocited": status.get("cocited"), "related": status.get("related"),
                     "truncated_citers": status.get("truncated_citers", []), "missing_seeds": status.get("missing_seeds", []),
                     "abstracts": kw_stats, "sem_threshold": SEM_THRESHOLD},
        "layout": {"W": W, "H": H, "YPX": YPX, "PAD_TOP": PAD_TOP, "PAD_BOTTOM": PAD_BOTTOM,
                   "minYear": min_year, "maxYear": max_year, "floorYear": floor_year, "olderFolded": older,
                   "noYearY": NOYEAR_Y, "home": home},
        "caveats": [
            "辺は OpenAlex が解決した参照関係のみ。辺が無いことは「引用なし」を意味しない。",
            "候補の階層は引用トポロジと語彙の類似度による機械的な分類で、内容上の関連を保証しない。最終判断は人間が行う。",
            "共引用は既知文献を引用する文献の参照リストから数えたもので、既知 2 件以上と共引用された 16 万件のうち上位 6,000 件だけ本体を取得している。",
            "意味ベース（TF-IDF）の類似度はタイトルと要旨の語彙の重なりで、要旨が OpenAlex に無い文献は低く出る。",
            "被引用数は世界全体の値（OpenAlex）。質や関連性の指標ではない。",
        ],
    }
    graph = {"meta": meta, "nodes": nodes, "edges": edges, "density": density, "kw": kw}
    out = HERE / "data" / "finder.json"
    out.write_text(json.dumps(graph, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    tpl = (HERE / "finder.html").read_text(encoding="utf-8")
    assert "__GRAPH_DATA__" in tpl
    payload = json.dumps(graph, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace("\ufffd", "\\ufffd")
    frag = tpl.replace("__GRAPH_DATA__", payload)
    (HERE / "artifact.html").write_text(frag, encoding="utf-8")
    m = re.search(r"<title>.*?</title>\n?", frag)
    title_tag = m.group(0).strip() if m else "<title>引用地層図</title>"
    body = frag.replace(m.group(0), "", 1) if m else frag
    html = ("<!doctype html>\n<html lang=\"ja\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
            f"{title_tag}\n</head>\n<body>\n{body}\n</body>\n</html>\n")
    (HERE / "index.html").write_text(html, encoding="utf-8")
    print(f"nodes={len(nodes)} edges={len(edges)} finder.json={out.stat().st_size // 1024} KB index.html={len(html.encode()) // 1024} KB")
    # 上位候補の報告
    top = sorted((n for n in nodes if n["tier"] == 1), key=lambda n: -n["sc"])[:15]
    print("\n-- tier 1 top by score --")
    for n in top:
        print(f"  {n['y']} | links {len(n['dc']) + len(n['db'])} cocite {n['cc']} coup {n['cp']} sim {n['ss']:.2f} | cited {n['c']} | {n['t'][:70]}")
    top3 = sorted((n for n in nodes if n["tier"] == 3), key=lambda n: -n["ss"])[:10]
    print("\n-- tier 3 (semantic only) top by similarity --")
    for n in top3:
        print(f"  {n['y']} | sim {n['ss']:.2f} -> {seed_ids and known_rows[n['ssi']]['note'] if n['ssi'] is not None else '-'} | {n['t'][:70]}")


if __name__ == "__main__":
    sys.exit(main())
