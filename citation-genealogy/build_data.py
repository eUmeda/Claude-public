#!/usr/bin/env python3
"""引用系譜ビューア データ整形スクリプト

raw データ (scite citation_graph の取得結果) を統合し、
  - data/graph.json   (整形済みグラフデータ)
  - index.html        (template.html にデータを埋め込んだ自己完結ビューア)
を生成する。

データの由来:
  - data/backward_scite.json      8起点の参照文献 (direction=out, depth=1, 打ち切りなし)
  - data/forward_keitt_scite.json Keitt 2000 の被引用サンプル60件 (打ち切りあり)

注意: scite は DOI に解決できた引用関係のみを返す。古い文献ほど参照リストの
解決率が低い (例: Whittle 1954 は7件のみ)。「未探索」と「引用なし」の区別は
graph.json の explored フィールドで保持する。
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent

# ---- 起点文献 (ユーザー指定の8件) --------------------------------------------
# lineage A = 確率場・中立景観の系譜 / B = 森林・林冠光環境の系譜
# note_ja は Claude による内容注記であり、引用関係データとは由来が異なる。
SEEDS = {
    "10.1093/biomet/41.3-4.434": {
        "key": "whittle1954", "label": "Whittle 1954", "lineage": "A",
        "authors": "P. Whittle",
        "venue": "Biometrika 41: 434–449",
        "note_ja": "平面上の定常確率過程の統計理論。Matérn 型共分散・SPDE アプローチの源流で、Lindgren et al. (2011) の直接の祖先。",
    },
    "10.1007/bf02275262": {
        "key": "gardner1987", "label": "Gardner 1987", "lineage": "A",
        "authors": "R.H. Gardner, B.T. Milne, M.G. Turner, R.V. O'Neill",
        "venue": "Landscape Ecology 1: 19–28",
        "note_ja": "ランダム地図による neutral landscape model の提唱。景観パターンを帰無モデルと比較する枠組みの基礎文献。",
    },
    "10.1023/a:1008193015770": {
        "key": "keitt2000", "label": "Keitt 2000", "lineage": "A",
        "authors": "T.H. Keitt",
        "venue": "Landscape Ecology 15: 479–493",
        "note_ja": "スペクトル合成による中立景観の生成と解析。フーリエ表現で空間自己相関を連続的に制御する。",
    },
    "10.1111/j.1467-9868.2011.00777.x": {
        "key": "lindgren2011", "label": "Lindgren 2011", "lineage": "A",
        "authors": "F. Lindgren, H. Rue, J. Lindström",
        "venue": "J. R. Stat. Soc. B 73: 423–498",
        "note_ja": "ガウス場と GMRF を SPDE で明示的に接続。Whittle (1954) を現代の空間統計計算へつないだ。",
    },
    "10.1093/aob/mci052": {
        "key": "monsi1953", "label": "Monsi & Saeki 1953/2005", "lineage": "B",
        "authors": "M. Monsi, T. Saeki",
        "venue": "Annals of Botany 95: 549–567（1953年原著の2005年英訳）",
        "note_ja": "植物群落内の光減衰（Beer–Lambert 則）と物質生産の理論。林分光環境研究の古典。DOI は2005年英訳のもの。時間軸上は原著1953年に配置。",
        "plot_year": 1953,
    },
    "10.2307/2963479": {
        "key": "pacala1996", "label": "Pacala 1996", "lineage": "B",
        "authors": "S.W. Pacala, C.D. Canham, J. Saponara, J.A. Silander Jr., R.K. Kobe, E. Ribbens",
        "venue": "Ecological Monographs 66: 1–43",
        "note_ja": "個体ベース森林動態モデル SORTIE の誤差解析。林冠光の伝達と実生更新をつなぐモデリングの基盤。",
    },
    "10.1139/x90-084": {
        "key": "canham1990", "label": "Canham 1990", "lineage": "B",
        "authors": "C.D. Canham, J.S. Denslow, W.J. Platt, J.R. Runkle, T.A. Spies, P.S. White",
        "venue": "Can. J. For. Res. 20: 620–631",
        "note_ja": "温帯林・熱帯林の閉鎖林冠下とギャップの光環境の比較測定。",
    },
    "10.1890/0012-9658(1999)080[1908:sholaw]2.0.co;2": {
        "key": "nicotra1999", "label": "Nicotra 1999", "lineage": "B",
        "authors": "A.B. Nicotra, R.L. Chazdon, S.V.B. Iriarte",
        "venue": "Ecology 80: 1908–1926",
        "note_ja": "熱帯湿潤林における光環境の空間異質性と木本実生の更新の対応関係を実測した研究。",
    },
}

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def clean_title(t):
    if not t:
        return "(no title)"
    t = TAG_RE.sub("", t)
    return WS_RE.sub(" ", t).strip()


def main():
    back = json.load(open(HERE / "data" / "backward_scite.json"))
    fwd = json.load(open(HERE / "data" / "forward_keitt_scite.json"))

    assert back["direction"] == "out" and back["truncated"] is False
    seed_dois = set(back["seeds"])
    assert seed_dois == set(SEEDS.keys()), "seed set mismatch"

    papers = dict(back["papers"])  # doi -> {title, year}

    # ---- 辺の構築 ------------------------------------------------------------
    edges = []           # {s: citing, t: cited, kind}
    seen_edges = set()
    for e in back["edges"]:
        k = (e["s"], e["t"])
        if k in seen_edges or e["s"] == e["t"]:
            continue
        seen_edges.add(k)
        edges.append({"s": e["s"], "t": e["t"], "kind": "back"})

    keitt = "10.1023/a:1008193015770"
    fwd_overlap = []
    for c in fwd["citers"]:
        doi = c["doi"].lower()
        if doi in papers:
            fwd_overlap.append(doi)
        else:
            papers[doi] = {"title": c["title"], "year": c["year"]}
        k = (doi, keitt)
        if k not in seen_edges and doi != keitt:
            seen_edges.add(k)
            edges.append({"s": doi, "t": keitt, "kind": "fwd"})

    # ---- ノードの構築 --------------------------------------------------------
    cited_by_seed = defaultdict(list)   # doi -> [seed keys が引用]
    cites_seed = defaultdict(list)      # doi -> [seed keys を引用]
    for e in edges:
        if e["s"] in SEEDS and e["t"] not in SEEDS:
            cited_by_seed[e["t"]].append(SEEDS[e["s"]]["key"])
        if e["t"] in SEEDS and e["s"] not in SEEDS:
            cites_seed[e["s"]].append(SEEDS[e["t"]]["key"])

    in_deg = defaultdict(int)
    out_deg = defaultdict(int)
    for e in edges:
        in_deg[e["t"]] += 1
        out_deg[e["s"]] += 1

    seed_lineage = {v["key"]: v["lineage"] for v in SEEDS.values()}

    nodes = []
    for doi, p in papers.items():
        seed = SEEDS.get(doi)
        citers = sorted(set(cited_by_seed.get(doi, [])))
        refs_to_seeds = sorted(set(cites_seed.get(doi, [])))
        lineages = {seed_lineage[k] for k in citers}
        if seed:
            lineage = seed["lineage"]
        elif lineages == {"A", "B"}:
            lineage = "AB"          # 系譜間ブリッジ (両系譜の起点から引用される祖先)
        elif lineages:
            lineage = lineages.pop()
        elif refs_to_seeds:
            lineage = "F"           # 後続文献 (起点を引用する側)
        else:
            lineage = None
        year = p.get("year")
        node = {
            "id": doi,
            "title": clean_title(p.get("title")),
            "year": year,
            "plotYear": (seed or {}).get("plot_year") or year,
            "isSeed": bool(seed),
            "lineage": lineage,
            "seedCiters": citers,        # このノードを引用している起点
            "seedRefs": refs_to_seeds,   # このノードが引用している起点
            "inDeg": in_deg.get(doi, 0),
            "outDeg": out_deg.get(doi, 0),
            "explored": {
                "back": "partial" if seed else "none",   # partial = scite が DOI 解決できた分のみ
                "fwd": "sample" if doi == keitt else "none",
            },
        }
        if seed:
            node.update({
                "seedKey": seed["key"], "label": seed["label"],
                "authors": seed["authors"], "venue": seed["venue"],
                "noteJa": seed["note_ja"],
            })
        nodes.append(node)

    # ---- 検証 ----------------------------------------------------------------
    ids = {n["id"] for n in nodes}
    for e in edges:
        assert e["s"] in ids and e["t"] in ids, f"dangling edge {e}"
        assert e["s"] != e["t"]
    assert sum(1 for n in nodes if n["isSeed"]) == 8
    bridges = [n for n in nodes if n["lineage"] == "AB"]
    assert any(n["id"] == "10.2307/2261007" for n in bridges), "expected bridge missing"
    shared = [n for n in nodes if not n["isSeed"] and len(n["seedCiters"]) >= 2]
    no_year = [n["id"] for n in nodes if not n["plotYear"]]

    # 起点ごとの参照数は実際に記録された辺から数える (scite の seed_coverage は
    # 4起点で実辺数と1件ずれるため、報告値は参考としてのみ保持する)
    seed_out = {doi: out_deg.get(doi, 0) for doi in SEEDS}
    meta = {
        "generated": "2026-09-22",
        "source": "scite citation_graph (MCP) 2026-09-22 取得",
        "coverage": {
            "backward": "8起点の参照文献・DOI解決分すべて (打ち切りなし)",
            "forward": "Keitt 2000 の被引用のみ60件サンプル (打ち切りあり)。他の7起点の被引用は未取得。",
            "seed_ref_counts": seed_out,
            "seed_ref_counts_scite_reported": back["seed_coverage"],
        },
        "counts": {
            "nodes": len(nodes), "edges": len(edges),
            "shared_ancestors": len(shared), "bridges": len(bridges),
            "fwd_overlap_with_backward": len(fwd_overlap),
            "no_year": len(no_year),
        },
        "caveats": [
            f"scite は DOI に解決できた引用関係のみを返すため、古い文献ほど参照リストが過少 (例: Whittle 1954 は{seed_out['10.1093/biomet/41.3-4.434']}件)。",
            "被引用数(全世界)は未取得。ノードの大きさは「この図の中で参照されている数」を表す。",
            "後続文献が Keitt 以外の起点も引用しているかは未調査 (前方探索は Keitt のみ)。",
            "note_ja は Claude による内容注記であり、引用関係の事実とは区別すること。",
        ],
    }

    graph = {"meta": meta, "nodes": nodes, "edges": edges}
    out = HERE / "data" / "graph.json"
    out.write_text(json.dumps(graph, ensure_ascii=False, indent=1), encoding="utf-8")

    tpl = (HERE / "template.html").read_text(encoding="utf-8")
    marker = "__GRAPH_DATA__"
    assert marker in tpl, "template marker missing"
    # "<" を < にエスケープ: 外部API由来のタイトルや DOI に "</script" 等の
    # 断片が含まれても <script> ブロックが終端されない (JSON としても妥当なまま)
    payload = json.dumps(graph, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    assert "<" not in payload
    frag = tpl.replace(marker, payload)

    # Artifact 用: フラグメント (公開時に doctype/head/body が付与される)
    (HERE / "artifact.html").write_text(frag, encoding="utf-8")

    # GitHub Pages 用: 完全な HTML 文書 (<title> を head へ移動)
    m = re.search(r"<title>.*?</title>\n?", frag)
    title_tag = m.group(0).strip() if m else "<title>引用地層図</title>"
    body = frag.replace(m.group(0), "", 1) if m else frag
    html = (
        "<!doctype html>\n<html lang=\"ja\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
        f"{title_tag}\n</head>\n<body>\n{body}\n</body>\n</html>\n"
    )
    (HERE / "index.html").write_text(html, encoding="utf-8")

    years = sorted(n["plotYear"] for n in nodes if n["plotYear"])
    print(f"nodes={len(nodes)} edges={len(edges)} shared={len(shared)} bridges={len(bridges)}")
    print(f"year range: {years[0]}–{years[-1]}  no_year={no_year}")
    print(f"fwd/back overlap: {fwd_overlap}")
    print(f"wrote {out} and index.html ({len(html)//1024} KB)")


if __name__ == "__main__":
    sys.exit(main())
