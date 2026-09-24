#!/usr/bin/env python3
"""見落とし検出ビューア（v0.3）のデータ整形・ページ生成

入力: data/known_list.csv と fetch_crawl.py の出力 data/crawl/*.json
出力:
  - data/finder.json   整形済み（ノード・辺・索引・レイアウト・統計・holdout 評価）
  - data/candidates.csv 候補一覧（known_list.csv に貼れる列順）
  - index.html         finder.html にデータを埋め込んだ自己完結ページ（GitHub Pages 用）
  - artifact.html      claude.ai Artifact 用フラグメント

候補の階層（tier）は finder_pipeline.py を参照:
  1 要確認        既知リストの 2 件以上と直接の引用関係（引用 or 被引用）
  2 関連の可能性  「確かな」つながり（直接 / 共引用の割合 / 参照共有）が 2 本以上
  3 意味ベースの保険  引用ではつながらないが語彙が近い（共通語幹 3 語以上・上限付き）、または OpenAlex の related_works
  5 既知の別版    既知文献と同じ論文の別レコード（類似度 0.8 以上・年差 1 以内・筆頭著者一致）
  0 海            上記以外（既知 1 件だけとつながる文献が大半）
"""
import base64
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from finder_pipeline import CONFIG, holdout, merge_aliases, norm_doi, run
from finder_signals import short, tokens

HERE = Path(__file__).parent
CRAWL = HERE / "data" / "crawl"
CLUSTER_ORDER = ["nlm", "field", "light", "ms", "forest", "evo", "stat", "lai"]
CLUSTER_LABEL = {
    "nlm": "中立景観モデル", "field": "確率場・空間統計", "light": "林床光環境", "ms": "群落光合成（Monsi–Saeki）",
    "forest": "森林動態", "evo": "分散・進化", "stat": "空間統計（生態）", "lai": "LAI・葉群計測",
}
HOLDOUT_PHASE = 2   # 通常ビルドでも phase <= 2（8 件）を既知にした holdout 評価を 1 回走らせる
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


def topic_ok(w, seed_topics):
    pt = (w.get("primary_topic") or {}).get("id")
    return bool(pt and pt in seed_topics)


def main():
    seeds = load("seeds.json", {})
    if not seeds:
        sys.exit("data/crawl/seeds.json がありません。先に fetch_crawl.py を実行してください。")
    status = load("status.json", {})
    related_ids = {short(r) for s in seeds.values() for r in s.get("related_works") or []}

    # ---- works 表と層 ----------------------------------------------------------
    works, layer = {}, {}
    for key, s in seeds.items():
        wid = short(s["id"])
        works[wid] = s
        layer[wid] = "known"
    for name, lay in (("refs.json", "ref"), ("citers.json", "citer"), ("cocited.json", "cocited"), ("cocited1.json", "cocited1"), ("related.json", "related")):
        for w in load(name, []):
            wid = short(w["id"])
            if wid not in works:
                works[wid] = w
                layer[wid] = lay
    seed_key = {short(s["id"]): k for k, s in seeds.items()}
    seeds_by_id = {short(s["id"]): s for s in seeds.values()}
    print(f"works: {len(works)}  layers: {Counter(layer.values())}")

    # ---- 別名統合 ----------------------------------------------------------------
    works, alias, merged = merge_aliases(works, set(seed_key))
    related_ids = {alias.get(r, r) for r in related_ids}
    print(f"merged aliases: {len(merged)} -> works {len(works)}")

    seed_ids = list(seed_key)
    seed_cluster = {sid: seeds_by_id[sid]["cluster"] for sid in seed_ids}
    seed_index = {sid: i for i, sid in enumerate(seed_ids)}
    seed_topics = set()
    for sid in seed_ids:
        s = works[sid]
        if (s.get("primary_topic") or {}).get("id"):
            seed_topics.add(s["primary_topic"]["id"])
        for t in s.get("topics") or []:
            if t.get("id"):
                seed_topics.add(t["id"])

    # ---- パイプライン ------------------------------------------------------------
    topo, sem, res, info = run(works, seed_ids, seed_cluster, related_ids)
    tiers = {w: r["tier"] for w, r in res.items()}
    for sid in seed_ids:
        tiers[sid] = -1
    tier_counts = Counter(tiers.values())
    print(f"tiers: known={tier_counts[-1]} T1={tier_counts[1]} T2={tier_counts[2]} T3={tier_counts[3]} dup={tier_counts[5]} sea={tier_counts[0]}")
    print(f"semantic: {info['semantic']}  citers={info['topology']['n_citers']}")

    # ---- holdout 評価 ------------------------------------------------------------
    ho = holdout(works, seeds_by_id, related_ids, HOLDOUT_PHASE)
    print(f"holdout(phase<={HOLDOUT_PHASE}): known={ho['known']} hidden={ho['hidden']} pool={ho['pool']} tiers={ho['tiers']} recall={ho['recall']}")
    for r in sorted(ho["rows"], key=lambda r: (r["rank"] or 10**9)):
        print(f"   {r['key']:<20} tier={r['tier']} rank={r['rank']} N={r['N']} direct={r['direct']} S={r['S']:.2f} sim={r['sim']:.2f} nn={r['nn']} pool_links={r['pool_links']}")

    # ---- クラスタ割当 ------------------------------------------------------------
    cluster_of = {}
    for wid in works:
        if wid in seed_key:
            cluster_of[wid] = seed_cluster[wid]
            continue
        t = topo.get(wid)
        aff = Counter()
        if t:
            for e in t["ev"]:
                if not (e[1] & 32):
                    aff[seed_cluster[e[0]]] += e[2]
        if aff:
            top = max(aff.values())
            cluster_of[wid] = [c for c in CLUSTER_ORDER if aff.get(c) == top][0]
        else:
            cluster_of[wid] = sem.get(wid, {}).get("cluster") or CLUSTER_ORDER[0]

    # ---- 辺（既知に触れるもの＋候補どうし。海→候補の大量の辺は件数 ind にだけ反映） ----------
    # 拡張プール（cocited1）のうち海に残ったものはページに埋め込まない（判定には使い、描画には出さない）
    ids = [wid for wid in works if not (layer.get(wid) == "cocited1" and tiers[wid] == 0)]
    index = {wid: i for i, wid in enumerate(ids)}
    print(f"embedded nodes: {len(ids)} (cocited1 の海 {len(works) - len(ids)} 件は非埋め込み)")
    refs_of = {wid: {short(r) for r in w.get("referenced_works") or []} for wid, w in works.items()}
    in_deg = Counter()
    edges = []
    for wid in works:
        for rs in refs_of[wid]:
            if rs in works and rs != wid:
                in_deg[rs] += 1
                # 埋め込む辺: どちらかが既知、または（両方が候補で）どちらかが要確認
                if wid in index and rs in index and (tiers[wid] == -1 or tiers[rs] == -1 or (tiers[wid] > 0 and tiers[rs] > 0 and (tiers[wid] == 1 or tiers[rs] == 1))):
                    edges.append((index[wid], index[rs]))
    edges = sorted(set(edges))
    print(f"edges embedded: {len(edges)}  (in-set citations total: {sum(in_deg.values())})")

    # ---- ノード ------------------------------------------------------------------
    nodes = []
    for wid in ids:
        w = works[wid]
        tier = tiers[wid]
        t = topo.get(wid, {"S": 0.0, "N": 0, "ev": [], "direct": set(), "nw": 0, "generic": False})
        cites = sorted({seed_index[k] for k in t["direct"] if k in refs_of[wid]})
        cited_by = sorted({seed_index[k] for k in t["direct"] if wid in refs_of[k]})
        node = {
            "id": wid, "t": clean(w.get("title"), 140 if tier in (-1, 1) else 110 if tier != 0 else 72) or "(no title)",
            "y": w.get("publication_year"), "c": w.get("cited_by_count"), "cl": cluster_of[wid], "tier": tier,
            "ind": in_deg.get(wid, 0), "dc": cites, "db": cited_by,
        }
        if tier != 0:
            s = sem.get(wid, {})
            r = res.get(wid, {})
            node.update({
                "doi": norm_doi(w.get("doi")), "au": authors_of(w, 3 if tier in (-1, 1) else 2), "v": venue_of(w),
                "tp": clean((w.get("primary_topic") or {}).get("display_name"), 60), "ly": layer.get(wid, "known"),
                "sc": r.get("score", 0), "S": t["S"], "N": t["N"], "nw": t["nw"], "gen": t["generic"],
                "ev": [[seed_index[e[0]], e[1], e[2], e[3], e[4], e[5]] for e in t["ev"][:8]],
                "ss": s.get("sim", 0), "ssi": seed_index.get(s.get("nn")), "kt": s.get("kt", []),
                "scl": s.get("simc", 0), "scn": s.get("cluster"),
                "tm": topic_ok(w, seed_topics), "rl": wid in related_ids, "dup": r.get("dup", False),
                "nref": len(refs_of[wid]), "hasAb": bool(w.get("abstract")),
            })
        if tier == -1:
            node.update({"key": w["key"], "cluster": w["cluster"], "phase": w["phase"], "note": w["note"],
                         "ab": clean(w.get("abstract"), 1500), "ki": seed_index[wid], "nref": len(refs_of[wid]),
                         "hasAb": bool(w.get("abstract"))})
        nodes.append(node)

    # ---- レイアウト ------------------------------------------------------------
    W, YPX = 6000.0, 40.0
    PAD_TOP, PAD_BOTTOM = 80, 100
    years = [n["y"] for n in nodes if n["y"]]
    known_years = [n["y"] for n in nodes if n["tier"] == -1 and n["y"]]
    floor_year = max(min(years), min(known_years) - 20)
    max_year, min_year = max(years) + 1, floor_year - 1
    H = PAD_TOP + (max_year - min_year) * YPX + PAD_BOTTOM
    NOYEAR_Y = H - PAD_BOTTOM / 2
    y_of = lambda yr: PAD_TOP + (max_year - max(yr, floor_year)) * YPX
    older = sum(1 for y in years if y < floor_year)
    home = {c: W * (0.06 + 0.88 * i / (len(CLUSTER_ORDER) - 1)) for i, c in enumerate(CLUSTER_ORDER)}
    pitch = home[CLUSTER_ORDER[1]] - home[CLUSTER_ORDER[0]]
    ROWS = 8

    def radius(n):
        if n["tier"] == -1:
            return 9.0
        if n["tier"] == 1:
            return 4.2 + min(2.5, 0.5 * math.log1p(n["ind"]))
        if n["tier"] in (2, 3, 5):
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
    bands = defaultdict(list)
    for n in nodes:
        bands[(max(n["y"], floor_year) if n["y"] else 0, n["_row"])].append(n)
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

    # ---- 密度（俯瞰用: 年 × クラスタ の件数と候補件数） ----------------------------------
    ci = {c: i for i, c in enumerate(CLUSTER_ORDER)}
    # 深さ（rank）別: 1 既知 / 2 要確認 / 3 関連 / 4 意味・別版 / 5 海。ビューアは深さ以下を合算して帯にする
    RANK = {-1: 0, 1: 1, 2: 2, 3: 3, 5: 3, 0: 4}
    density = defaultdict(lambda: [[0] * len(CLUSTER_ORDER) for _ in range(5)])
    for n in nodes:
        if n["y"]:
            density[max(n["y"], floor_year)][RANK[n["tier"]]][ci[n["cl"]]] += 1
    density = {str(y): v for y, v in sorted(density.items())}

    # ---- 索引 ----------------------------------------------------------------------
    kw, kw_stats = build_keyword_index([(i, (works[n["id"]].get("title") or "") + " " + (works[n["id"]].get("abstract") or "")) for i, n in enumerate(nodes)])
    print(f"keyword index: {kw_stats}")

    # ---- meta ---------------------------------------------------------------------
    known_rows = [{"i": seed_index[sid], "key": seed_key[sid], "cluster": seed_cluster[sid], "phase": seeds_by_id[sid]["phase"],
                   "note": seeds_by_id[sid]["note"], "year": works[sid].get("publication_year"),
                   "cited": works[sid].get("cited_by_count"), "refs": len(refs_of[sid]),
                   "citers": (status.get("seeds", {}).get(seed_key[sid], {}) or {}).get("citers"),
                   "node": index[sid]} for sid in seed_ids]
    coverage = {
        "refs": status.get("refs"), "cocited": status.get("cocited"), "cocited1": status.get("cocited1"), "related": status.get("related"),
        "truncated_citers": status.get("truncated_citers", []), "missing_seeds": status.get("missing_seeds", []),
        "abstracts": kw_stats, "merged": len(merged), "merged_examples": merged[:40],
        "no_abstract_known": [seeds_by_id[s]["note"] for s in seed_ids if not works[s].get("abstract")],
        "no_refs_known": [seeds_by_id[s]["note"] for s in seed_ids if not refs_of[s]],
        "semantic": info["semantic"], "config": CONFIG,
    }
    meta = {
        "version": "0.3.1", "generated": "2026-09-22", "source": "OpenAlex (2026-09-22 取得)",
        "clusters": CLUSTER_ORDER, "clusterLabel": CLUSTER_LABEL, "known": known_rows,
        "counts": {"nodes": len(nodes), "edges": len(edges), "known": tier_counts[-1], "t1": tier_counts[1],
                   "t2": tier_counts[2], "t3": tier_counts[3], "dup": tier_counts[5],
                   "sea": sum(1 for n in nodes if n["tier"] == 0),   # 埋め込んだ海だけ数える
                   "max_cited": max((n["c"] or 0) for n in nodes), "max_ind": max(n["ind"] for n in nodes)},
        "coverage": coverage, "holdout": ho,
        "layout": {"W": W, "H": H, "YPX": YPX, "PAD_TOP": PAD_TOP, "PAD_BOTTOM": PAD_BOTTOM, "pitch": pitch,
                   "minYear": min_year, "maxYear": max_year, "floorYear": floor_year, "olderFolded": older,
                   "noYearY": NOYEAR_Y, "home": home},
        "caveats": [
            "辺は OpenAlex が解決した参照関係のみ。辺が無いことは「引用なし」を意味しない。",
            "候補の階層は引用トポロジと語彙の類似度による機械的な分類で、内容上の関連を保証しない。最終判断は人間が行う。",
            "共引用は既知文献を引用する文献の参照リストから数え、既知 2 件以上と共引用された約 16 万件のうち上位 6,000 件だけ本体を取得している。既知 1 件だけと共引用された文献はクロールに入っていない。",
            "意味ベース（TF-IDF）の類似度はタイトルと要旨の語彙の重なりで、要旨が OpenAlex に無い文献は低く出る。言い換えの遠い文献は拾えない。",
            "被引用数は世界全体の値（OpenAlex）。質や関連性の指標ではない。",
        ],
    }
    graph = {"meta": meta, "nodes": nodes, "edges": edges, "density": density, "kw": kw}
    out = HERE / "data" / "finder.json"
    out.write_text(json.dumps(graph, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # ---- 候補 CSV ------------------------------------------------------------------
    with open(HERE / "data" / "candidates.csv", "w", encoding="utf-8", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["doi", "cluster", "phase", "note", "year", "tier", "score", "S_topo", "N_link", "direct", "sim", "nearest_known", "generic", "openalex"])
        for n in sorted((n for n in nodes if n["tier"] > 0), key=lambda n: (n["tier"], -n["sc"])):
            wr.writerow([n.get("doi") or "", n["cl"], 4, n["t"][:100], n["y"], n["tier"], n["sc"], n["S"], n["N"], len(n["dc"]) + len(n["db"]),
                         n["ss"], known_rows[n["ssi"]]["note"] if n.get("ssi") is not None else "", int(n["gen"]), "https://openalex.org/" + n["id"]])

    # ---- HTML -----------------------------------------------------------------------
    tpl = (HERE / "finder.html").read_text(encoding="utf-8")
    assert "__GRAPH_DATA__" in tpl
    # JSON 文字列として <script type="application/json"> に埋める。< は \u003c に逃がし（</script> 対策）、
    # U+FFFD は Artifact 公開が拒むので \ufffd に逃がす。NaN/Infinity は JSON.parse できないので禁止
    payload = json.dumps(graph, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c").replace("\ufffd", "\\ufffd")
    json.loads(payload)   # 埋め込み前に妥当な JSON であることを確認
    assert "</" not in payload and "<" not in payload
    frag = tpl.replace("__GRAPH_DATA__", payload)
    (HERE / "artifact.html").write_text(frag, encoding="utf-8")
    m = re.search(r"<title>.*?</title>\n?", frag)
    title_tag = m.group(0).strip() if m else "<title>引用地層図</title>"
    body = frag.replace(m.group(0), "", 1) if m else frag
    html = ("<!doctype html>\n<html lang=\"ja\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
            f"{title_tag}\n</head>\n<body>\n{body}\n</body>\n</html>\n")
    (HERE / "index.html").write_text(html, encoding="utf-8")
    size_mb = len(html.encode()) / 1024 / 1024
    print(f"nodes={len(nodes)} edges={len(edges)} finder.json={out.stat().st_size // 1024} KB index.html={size_mb:.1f} MB")
    if size_mb > 15.5:
        sys.exit("index.html が 15.5 MB を超えました。埋め込み量を減らしてください。")
    top = sorted((n for n in nodes if n["tier"] == 1), key=lambda n: -n["sc"])[:12]
    print("\n-- tier 1 top by score --")
    for n in top:
        print(f"  {n['y']} | S={n['S']:.2f} N={n['N']} direct={len(n['dc']) + len(n['db'])} sim={n['ss']:.2f} gen={n['gen']} | cited {n['c']} | {n['t'][:66]}")
    print("\n-- tier 5 (duplicates of known) --")
    for n in (n for n in nodes if n["tier"] == 5):
        print(f"  {n['y']} sim={n['ss']} -> {known_rows[n['ssi']]['note']} | {n['t'][:70]}")
    print("\n-- tier 3 (semantic only) top by similarity --")
    for n in sorted((n for n in nodes if n["tier"] == 3), key=lambda n: -n["ss"])[:10]:
        print(f"  {n['y']} sim={n['ss']:.2f} kt={n['kt']} -> {known_rows[n['ssi']]['note'] if n['ssi'] is not None else '-'} | {n['t'][:60]}")
    print("\n-- generic --")
    for n in (n for n in nodes if n.get("gen")):
        print(f"  {n['y']} nw={n['nw']} N={n['N']} | {n['t'][:70]}")


if __name__ == "__main__":
    sys.exit(main())
