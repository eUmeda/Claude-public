#!/usr/bin/env python3
"""引用系譜ビューア データ整形スクリプト（v0.2: OpenAlex 対応）

raw データを統合し、
  - data/graph.json   (整形済みグラフデータ・レイアウト座標込み)
  - index.html        (template.html にデータを埋め込んだ自己完結ビューア)
  - artifact.html     (claude.ai Artifact 公開用フラグメント)
を生成する。

データの由来:
  - data/openalex/seeds.json      8起点の work レコード
  - data/openalex/refs.json       起点の参照文献（1ホップ・参照リスト付き）
  - data/openalex/refs_hop2.json  参照文献の参照文献（2ホップ・参照リスト付き）
  - data/openalex/citers_<key>.json  各起点の被引用文献（取得できた場合のみ）
  - data/forward_keitt_scite.json v0.1 の Scite 由来 Keitt 2000 被引用サンプル。
    OpenAlex の被引用データが無い場合の暫定代替として前方層に使う。
  - data/backward_scite.json      v0.1 比較用（本スクリプトでは使わない）

ノード = 起点 + 1ホップ参照 + 2ホップ参照 + 被引用文献。
辺 = 取得済みノード集合の中で referenced_works が示す引用関係すべて（citing → cited）。
「未探索」と「引用なし」の区別は explored フィールドで保持する。
"""
import json
import math
import re
import sys
from collections import defaultdict, deque
from pathlib import Path

HERE = Path(__file__).parent
OA = HERE / "data" / "openalex"

# ---- 起点文献 (ユーザー指定の8件) --------------------------------------------
# lineage A = 確率場・中立景観の系譜 / B = 森林・林冠光環境の系譜
# note_ja は Claude による内容注記であり、引用関係データとは由来が異なる。
SEEDS = {
    "whittle1954": {
        "label": "Whittle 1954", "lineage": "A",
        "note_ja": "平面上の定常確率過程の統計理論。Matérn 型共分散・SPDE アプローチの源流で、Lindgren et al. (2011) の直接の祖先。",
    },
    "gardner1987": {
        "label": "Gardner 1987", "lineage": "A",
        "note_ja": "ランダム地図による neutral landscape model の提唱。景観パターンを帰無モデルと比較する枠組みの基礎文献。",
    },
    "keitt2000": {
        "label": "Keitt 2000", "lineage": "A",
        "note_ja": "スペクトル合成による中立景観の生成と解析。フーリエ表現で空間自己相関を連続的に制御する。",
    },
    "lindgren2011": {
        "label": "Lindgren 2011", "lineage": "A",
        "note_ja": "ガウス場と GMRF を SPDE で明示的に接続。Whittle (1954) を現代の空間統計計算へつないだ。",
    },
    "monsi1953": {
        "label": "Monsi & Saeki 1953/2005", "lineage": "B",
        "note_ja": "植物群落内の光減衰（Beer–Lambert 則）と物質生産の理論。林分光環境研究の古典。DOI は2005年英訳のもの。時間軸上は原著1953年に配置。",
        "plot_year": 1953,
    },
    "pacala1996": {
        "label": "Pacala 1996", "lineage": "B",
        "note_ja": "個体ベース森林動態モデル SORTIE の誤差解析。林冠光の伝達と実生更新をつなぐモデリングの基盤。",
    },
    "canham1990": {
        "label": "Canham 1990", "lineage": "B",
        "note_ja": "温帯林・熱帯林の閉鎖林冠下とギャップの光環境の比較測定。",
    },
    "nicotra1999": {
        "label": "Nicotra 1999", "lineage": "B",
        "note_ja": "熱帯湿潤林における光環境の空間異質性と木本実生の更新の対応関係を実測した研究。",
    },
}
# 横位置の基準（0..1）。系譜Aを左、Bを右に置く。
SEED_HOME = {
    "whittle1954": 0.12, "lindgren2011": 0.16, "gardner1987": 0.30, "keitt2000": 0.34,
    "nicotra1999": 0.64, "pacala1996": 0.70, "monsi1953": 0.80, "canham1990": 0.86,
}

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def clean_text(t, limit=None):
    if not t:
        return None
    t = WS_RE.sub(" ", TAG_RE.sub("", t)).strip()
    if limit and len(t) > limit:
        t = t[:limit - 1] + "…"
    return t or None


def short_id(oa_id):
    return oa_id.rsplit("/", 1)[-1] if oa_id else None


def norm_doi(doi):
    if not doi:
        return None
    return doi.lower().replace("https://doi.org/", "").strip() or None


def authors_of(w):
    names = [a.get("author", {}).get("display_name") for a in (w.get("authorships") or [])]
    names = [n for n in names if n]
    if not names:
        return None
    if len(names) > 3:
        return ", ".join(names[:3]) + f" ほか{len(names) - 3}名"
    return ", ".join(names)


def venue_of(w):
    loc = w.get("primary_location") or {}
    src = loc.get("source") or {}
    return src.get("display_name") or loc.get("raw_source_name") or None


def hash01(s):
    """DOI/ID から決定的な擬似乱数 (0..1)。template.html の hash01 と同じ FNV-1a"""
    h = 2166136261
    for ch in s:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return (h % 10000) / 10000


STOPWORDS = set("""
a an the and or of in on at to for from by with without as is are was were be been being this that these those
it its into than then there their they them we our us you your he she his her not no nor but if so such which who
whom whose what when where why how all any both each few more most other some own same very can will just should
may might must also between among over under during before after above below up down out off again further once
here about against because until while do does did doing have has had having only own too s t via use used using
based results result study studies show shows shown found data model models analysis approach method methods
paper present presented effect effects two three one however within across using new high low large small
""".split())
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-]+")


def stem(t):
    """軽い語幹処理（複数形・-ies のみ）。ビューア側の query 正規化と同じ規則にする"""
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 4 and t.endswith("es") and not t.endswith("ss"):
        return t[:-2] if t.endswith(("shes", "ches", "xes", "zes")) else t[:-1]
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def tokenize(text):
    out = set()
    for t in TOKEN_RE.findall(text.lower()):
        t = t.strip("-")
        if len(t) < 3 or t in STOPWORDS or t.isdigit():
            continue
        out.add(stem(t))
    return out


def varint_bytes(values):
    b = bytearray()
    for v in values:
        while v >= 0x80:
            b.append((v & 0x7F) | 0x80)
            v >>= 7
        b.append(v)
    return bytes(b)


def build_keyword_index(nodes):
    """要旨の語ごとに、その語を含むノード添字の昇順リストをデルタ varint で連結し base64 で 1 本の
    文字列にする（vocab / off / blob）。ビューア側は語彙を前方一致で引いて postings を復号する。
    df < 2 の語と、全体の 25% 超に現れる語は落とす。"""
    import base64
    postings = defaultdict(list)
    n_docs = 0
    for i, n in enumerate(nodes):
        text = n.get("_abs_text") or ""
        if not text:
            continue
        n_docs += 1
        for t in tokenize(text):
            postings[t].append(i)
    max_df = max(2, int(0.25 * max(1, n_docs)))
    vocab = sorted(t for t, lst in postings.items() if 2 <= len(lst) <= max_df)
    blob = bytearray()
    offsets = []
    total = 0
    for t in vocab:
        lst = postings[t]
        offsets.append(len(blob))
        prev = -1
        deltas = []
        for i in lst:
            deltas.append(i - prev - 1)
            prev = i
        blob += varint_bytes([len(lst)] + deltas)
        total += len(lst)
    offsets.append(len(blob))
    index = {"vocab": vocab, "off": offsets, "blob": base64.b64encode(bytes(blob)).decode("ascii")}
    stats = {"docs_with_abstract": n_docs, "terms": len(vocab), "postings": total,
             "blob_kb": len(index["blob"]) // 1024}
    return index, stats


def load_json(p, default=None):
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def main():
    seeds_raw = load_json(OA / "seeds.json")
    if not seeds_raw:
        sys.exit("data/openalex/seeds.json がありません。先に fetch_openalex.py を実行してください。")
    refs1 = load_json(OA / "refs.json", [])
    hop2 = load_json(OA / "refs_hop2.json", {"truncated": None, "requested": 0, "works": []})
    status = load_json(OA / "fetch_status.json", {})
    # 2ホップ層・後続層の要旨（fetch_openalex.py --abstracts）。ビューアには埋め込まず索引のみに使う
    abstracts_extra = load_json(OA / "abstracts.json", {})

    # ---- ノード表: OpenAlex 短縮ID をキーにする --------------------------------
    works = {}          # id -> raw work
    hop_of = {}         # id -> 0 (起点) / 1 / 2 / "F"
    seed_key_of = {}    # id -> seed key
    for key, w in seeds_raw.items():
        wid = short_id(w["id"])
        works[wid] = w
        hop_of[wid] = 0
        seed_key_of[wid] = key
    for w in refs1:
        wid = short_id(w["id"])
        if wid not in works:
            works[wid] = w
            hop_of[wid] = 1
    for w in hop2["works"]:
        wid = short_id(w["id"])
        if wid not in works:
            works[wid] = w
            hop_of[wid] = 2

    # 被引用文献（OpenAlex）: citers_<key>.json があれば読む
    citer_files = sorted(OA.glob("citers_*.json"))
    citers_source = None
    fwd_seed_ids = set()  # 前方探索を実施した起点
    fwd_truncated = {}
    for p in citer_files:
        d = load_json(p)
        skey = d["seed"]
        fwd_seed_ids.add(short_id(d["seed_openalex_id"]))
        fwd_truncated[skey] = d.get("truncated", False)
        for w in d["citers"]:
            wid = short_id(w["id"])
            if wid not in works:
                works[wid] = w
                hop_of[wid] = "F"
        citers_source = "openalex"

    # 被引用文献の暫定代替: v0.1 Scite の Keitt 2000 サンプル（OpenAlex 分が無い場合のみ）
    scite_fwd = load_json(HERE / "data" / "forward_keitt_scite.json")
    scite_fwd_count = 0
    if not citer_files and scite_fwd:
        doi_to_id = {norm_doi(w.get("doi")): wid for wid, w in works.items() if norm_doi(w.get("doi"))}
        keitt_id = next(wid for wid, k in seed_key_of.items() if k == "keitt2000")
        for c in scite_fwd["citers"]:
            doi = norm_doi(c["doi"])
            wid = doi_to_id.get(doi)
            if wid is None:
                wid = "doi:" + doi
                works[wid] = {
                    "id": wid, "doi": "https://doi.org/" + doi, "title": c["title"],
                    "publication_year": c.get("year"), "cited_by_count": None,
                    "referenced_works": [], "type": None, "_scite": True,
                }
                hop_of[wid] = "F"
            works[wid].setdefault("_extra_refs", []).append(keitt_id)
            scite_fwd_count += 1
        citers_source = "scite-sample"
        fwd_seed_ids.add(keitt_id)
        fwd_truncated["keitt2000"] = True

    # ---- 辺: 取得済みノード集合内の referenced_works すべて ------------------
    ids = list(works.keys())
    index = {wid: i for i, wid in enumerate(ids)}
    out_adj = defaultdict(list)
    in_adj = defaultdict(list)
    edge_set = set()
    for wid, w in works.items():
        targets = [short_id(t) for t in (w.get("referenced_works") or [])]
        targets += w.get("_extra_refs", [])
        for t in targets:
            if t in works and t != wid and (wid, t) not in edge_set:
                edge_set.add((wid, t))
                out_adj[wid].append(t)
                in_adj[t].append(wid)
    edges = sorted(edge_set, key=lambda e: (index[e[0]], index[e[1]]))

    # ---- 系譜分類: 各起点から引用方向に到達できる集合（祖先） ---------------------
    MAX_REACH = 2   # 取得範囲（2ホップ）と同じ深さで系譜を判定する

    def bfs_depth(start):
        """start から引用方向へ MAX_REACH ホップ以内で辿れるノードと最短ホップ数。
        - 他の起点は到達点として記録するが、その先へは展開しない（各起点固有の祖先系譜にする。
          例: Nicotra → Pacala → Canham の祖先は Nicotra 由来には数えない）。
        - 深さを制限しないと、2ホップ層どうしの引用でつながって大半が「両系譜」になり
          ブリッジの意味が失われる（無制限だと 8,058 件中 4,984 件が AB になった）。"""
        depth = {start: 0}
        q = deque([start])
        while q:
            cur = q.popleft()
            if cur != start and cur in seed_key_of:
                continue
            if depth[cur] >= MAX_REACH:
                continue
            for nx in out_adj[cur]:
                if nx not in depth:
                    depth[nx] = depth[cur] + 1
                    q.append(nx)
        return depth

    seed_ids = {k: wid for wid, k in seed_key_of.items()}
    reach = {k: bfs_depth(wid) for k, wid in seed_ids.items()}   # key -> {id: hop}
    lineage_of_seed = {k: v["lineage"] for k, v in SEEDS.items()}

    # 起点を直接引用/被引用する関係
    seed_citers = defaultdict(list)   # id -> [seed keys がこのノードを直接引用]
    cites_seed = defaultdict(list)    # id -> [seed keys をこのノードが直接引用]
    for s, t in edges:
        if s in seed_key_of and t not in seed_key_of:
            seed_citers[t].append(seed_key_of[s])
        if t in seed_key_of and s not in seed_key_of:
            cites_seed[s].append(seed_key_of[t])

    nodes = []
    max_cited = max((w.get("cited_by_count") or 0) for w in works.values())
    for wid in ids:
        w = works[wid]
        key = seed_key_of.get(wid)
        anc_from = {k: d[wid] for k, d in reach.items() if wid in d and k != key}
        hop_a = min((d for k, d in anc_from.items() if lineage_of_seed[k] == "A"), default=None)
        hop_b = min((d for k, d in anc_from.items() if lineage_of_seed[k] == "B"), default=None)
        if key:
            lineage = lineage_of_seed[key]
        elif hop_a is not None and hop_b is not None:
            lineage = "AB"
        elif hop_a is not None:
            lineage = "A"
        elif hop_b is not None:
            lineage = "B"
        elif cites_seed.get(wid):
            lineage = "F"
        else:
            lineage = None
        year = w.get("publication_year")
        plot_year = (SEEDS[key].get("plot_year") if key else None) or year
        refs_total = len(w.get("referenced_works") or [])
        hop = hop_of[wid]
        if w.get("_scite"):
            explored_back = "none"        # scite サンプル: 参照リスト未取得
        elif hop in (0, 1):
            explored_back = "full"        # 参照リストの文献をすべて取得（=図内に全件）
        else:
            explored_back = "list"        # 参照リストの ID は既知だが文献は未取得（図内分のみ辺を描く）
        explored_fwd = "none"
        if wid in fwd_seed_ids:
            explored_fwd = "sample" if fwd_truncated.get(key) else "full"
        node = {
            "id": wid,
            "doi": norm_doi(w.get("doi")),
            "title": clean_text(w.get("title")) or "(no title)",
            "year": year,
            "plotYear": plot_year,
            "cited": w.get("cited_by_count"),
            "authors": authors_of(w),
            "venue": clean_text(venue_of(w), 80),
            "type": w.get("type"),
            "hop": hop,
            "isSeed": bool(key),
            "lineage": lineage,
            "hopA": hop_a, "hopB": hop_b,
            "seedAnc": sorted(anc_from.keys()),        # このノードへ到達する起点（推移的）
            "seedCiters": sorted(set(seed_citers.get(wid, []))),   # 直接引用する起点
            "seedRefs": sorted(set(cites_seed.get(wid, []))),      # 直接引用している起点
            "inDeg": len(in_adj[wid]),
            "outDeg": len(out_adj[wid]),
            "refsTotal": refs_total,
            "explored": {"back": explored_back, "fwd": explored_fwd},
        }
        ab = clean_text(w.get("abstract"), 1500)
        if ab:
            node["abstract"] = ab          # 起点・1ホップは本文を埋め込む（詳細パネルで表示）
            node["hasAbstract"] = True
        elif abstracts_extra.get(wid):
            node["hasAbstract"] = True     # 2ホップ層・後続層は索引のみ（本文は埋め込まない）
        node["_abs_text"] = ab or abstracts_extra.get(wid) or ""
        if key:
            node.update({"seedKey": key, "label": SEEDS[key]["label"], "noteJa": SEEDS[key]["note_ja"]})
        nodes.append(node)

    # ---- レイアウト（決定論的・Python 側で確定） ----------------------------------
    W = 3000.0
    YPX = 14.0
    PAD_TOP, PAD_BOTTOM = 60, 80
    years = [n["plotYear"] for n in nodes if n["plotYear"]]
    max_year, min_year = max(years) + 1, min(years) - 1
    H = PAD_TOP + (max_year - min_year) * YPX + PAD_BOTTOM
    NOYEAR_Y = H - PAD_BOTTOM / 2

    def y_of(y):
        return PAD_TOP + (max_year - y) * YPX

    def radius_of(n):
        if n["isSeed"]:
            return 11.0
        if n["lineage"] == "AB":
            return 5.5 + min(3.0, 0.6 * math.log1p(n["inDeg"]))
        if n["hop"] == 1 or n["lineage"] == "F":
            return 3.6 + min(2.5, 0.7 * math.log1p(n["inDeg"]))
        return 1.9 + min(2.6, 0.7 * math.log1p(n["inDeg"]))

    def home_x(n):
        if n["isSeed"]:
            return SEED_HOME[n["seedKey"]] * W
        anchors = n["seedAnc"] or n["seedRefs"]
        if anchors:
            mean = sum(SEED_HOME[k] for k in anchors) / len(anchors)
        else:
            mean = 0.5
        spread = 0.12 if n["hop"] == 1 else 0.22
        return (mean + (hash01(n["id"]) - 0.5) * 2 * spread) * W

    for n in nodes:
        n["r"] = round(radius_of(n), 2)
        n["x"] = home_x(n)
        base_y = y_of(n["plotYear"]) if n["plotYear"] else NOYEAR_Y
        # 年帯（14px）の中を3列に分け、列ごとに y をずらす（起点は中央列）
        row = 0 if n["isSeed"] else int(hash01(n["id"] + "row") * 3)
        n["_row"] = row
        n["y"] = base_y if n["isSeed"] else base_y + (row - 1) * 4.2 + (hash01(n["id"] + "y") - 0.5) * 1.5

    # 同じ年帯・同じ列の中で横方向の重なりを解消（1次元の反復押し出し）
    bands = defaultdict(list)
    for n in nodes:
        bands[(n["plotYear"] or 0, n["_row"])].append(n)
    GAP = 1.6
    for band in bands.values():
        if len(band) < 2:
            continue
        for _ in range(60):
            band.sort(key=lambda m: m["x"])
            moved = False
            for a, b in zip(band, band[1:]):
                need = a["r"] + b["r"] + GAP
                d = b["x"] - a["x"]
                if d < need:
                    push = (need - d) / 2
                    if a["isSeed"]:
                        b["x"] += 2 * push
                    elif b["isSeed"]:
                        a["x"] -= 2 * push
                    else:
                        a["x"] -= push
                        b["x"] += push
                    moved = True
            if not moved:
                break
        # 起点は固定し、それ以外を左右へ均等に押し戻す
        free = [m for m in band if not m["isSeed"]]
        if free:
            lo = min(m["x"] - m["r"] for m in free)
            hi = max(m["x"] + m["r"] for m in free)
            shift = 0.0
            if lo < 20:
                shift = 20 - lo
            elif hi > W - 20:
                shift = (W - 20) - hi
            for m in free:
                m["x"] = min(W - 20, max(20, m["x"] + shift))
    for n in nodes:
        n["x"] = round(n["x"], 1)
        n["y"] = round(n["y"], 1)
        n.pop("_row", None)

    # ---- キーワード索引（要旨の語 → ノード添字。タイトルは本文をそのまま埋め込むので索引不要） ----
    kw_index, kw_stats = build_keyword_index(nodes)
    for n in nodes:
        n.pop("_abs_text", None)

    # ---- 検証 ----------------------------------------------------------------
    for s, t in edges:
        assert s in index and t in index and s != t
    assert sum(1 for n in nodes if n["isSeed"]) == 8
    bridges = [n for n in nodes if n["lineage"] == "AB"]
    direct_bridges = [n for n in bridges if n["hopA"] == 1 and n["hopB"] == 1]
    shared_direct = [n for n in nodes if not n["isSeed"] and len(n["seedCiters"]) >= 2]
    shared_reach = [n for n in nodes if not n["isSeed"] and len(n["seedAnc"]) >= 2]
    no_year = [n["id"] for n in nodes if not n["plotYear"]]
    fwd_nodes = [n for n in nodes if n["lineage"] == "F"]

    hop_counts = {str(h): sum(1 for n in nodes if n["hop"] == h) for h in (0, 1, 2, "F")}
    seed_ref_counts = {k: {"total": len(seeds_raw[k]["referenced_works"]),
                           "in_graph": len(out_adj[seed_ids[k]])} for k in SEEDS}
    fwd_desc = ("未取得（OpenAlex の cites: 一覧クエリは共有 IP の無料予算が枯渇。API キーを置いて再取得すると全件入る）"
                if citers_source is None else
                f"v0.1 Scite サンプル（Keitt 2000 の被引用 {scite_fwd_count} 件・打ち切りあり）を暫定表示。OpenAlex 全件は API キー取得後に再実行"
                if citers_source == "scite-sample" else
                "OpenAlex cites: で各起点の被引用文献を取得 " + json.dumps(fwd_truncated))
    meta = {
        "generated": "2026-09-22",
        "version": "0.2",
        "source": "OpenAlex (2026-09-22 取得)",
        "coverage": {
            "backward": "8起点の参照文献（1ホップ）と、その参照文献の参照文献（2ホップ）を全件取得"
                        + ("（2ホップは上限で打ち切り）" if hop2.get("truncated") else "（打ち切りなし）"),
            "forward": fwd_desc,
            "citers_source": citers_source,
            "backward_mode": status.get("backward_mode"),
            "seed_ref_counts": seed_ref_counts,
            "hop_counts": hop_counts,
        },
        "counts": {
            "nodes": len(nodes), "edges": len(edges),
            "shared_ancestors_direct": len(shared_direct),
            "shared_ancestors_reach": len(shared_reach),
            "bridges": len(bridges), "bridges_direct": len(direct_bridges),
            "forward": len(fwd_nodes),
            "no_year": len(no_year),
            "max_cited": max_cited,
        },
        "layout": {"W": W, "H": H, "YPX": YPX, "PAD_TOP": PAD_TOP, "PAD_BOTTOM": PAD_BOTTOM,
                   "minYear": min_year, "maxYear": max_year, "noYearY": NOYEAR_Y},
        "caveats": [
            "辺は OpenAlex が解決した参照関係のみ。古い文献ほど参照リストが過少（例: Whittle 1954 の参照は "
            f"{seed_ref_counts['whittle1954']['total']} 件）。辺が無いことは「引用なし」を意味しない。",
            "2ホップ目の文献は参照リストの ID だけ既知で、その先の文献は取得していない（図内にある文献への辺だけ描く）。",
            "ノードの濃さは OpenAlex の世界全体の被引用数（対数スケール）。被引用数の多さは質や関連性ではなく、分野規模や年数の影響を強く受ける。",
            "系譜の分類（A/B/AB）は各起点から引用を2ホップ以内でたどって到達できるか（他の起点で経路は止める）による機械的分類で、内容上の系譜と一致するとは限らない。図内の辺は2ホップ層どうしの引用も含むため、辺をたどればさらに遠くまでつながる。",
            "note_ja は Claude による内容注記であり、引用関係の事実とは区別すること。",
        ],
    }

    # 埋め込み用の圧縮表現: 辺はノード添字のペア
    meta["coverage"]["abstracts"] = kw_stats
    graph = {
        "meta": meta,
        "nodes": nodes,
        "edges": [[index[s], index[t]] for s, t in edges],
        "kw": kw_index,
    }
    out = HERE / "data" / "graph.json"
    out.write_text(json.dumps(graph, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    tpl = (HERE / "template.html").read_text(encoding="utf-8")
    marker = "__GRAPH_DATA__"
    assert marker in tpl, "template marker missing"
    # "<" を < にエスケープ: 外部API由来のタイトル等に "</script" 断片が含まれても
    # <script> ブロックが終端されない (JSON としても妥当なまま)
    payload = json.dumps(graph, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    # OpenAlex 由来のタイトルに含まれる置換文字 U+FFFD は JSON エスケープにして埋め込む
    # （公開ツールがソース中の U+FFFD を「編集で欠けた文字」とみなして拒否するため。データは不変）
    payload = payload.replace("\ufffd", "\\ufffd")
    assert "<" not in payload and "\ufffd" not in payload
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

    # ---- 報告 ----------------------------------------------------------------
    print(f"nodes={len(nodes)} edges={len(edges)} hops={hop_counts}")
    print(f"bridges(AB, reachable from both)={len(bridges)}  direct(hop1 from both)={len(direct_bridges)}")
    print(f"shared ancestors: direct(>=2 seeds cite)={len(shared_direct)}  reach(>=2 seeds reach)={len(shared_reach)}")
    print(f"forward nodes={len(fwd_nodes)} (source={citers_source})  no_year={len(no_year)}")
    print(f"year range {min_year + 1}–{max_year - 1}; max cited_by_count={max_cited}")
    print(f"keyword index: {kw_stats}")
    print(f"wrote {out} ({out.stat().st_size // 1024} KB) and index.html ({len(html) // 1024} KB)")
    bridges.sort(key=lambda n: (-(len(n["seedAnc"])), -n["inDeg"]))
    print("\n-- direct bridges (hop1 from both lineages) --")
    for n in direct_bridges:
        print(f"  {n['year']} | {n['title'][:70]} | cited_by={n['cited']} | seeds={n['seedCiters']}")
    print(f"\n-- top bridges by number of reaching seeds (of {len(bridges)}) --")
    for n in bridges[:25]:
        print(f"  {n['year']} | hopA={n['hopA']} hopB={n['hopB']} | seeds={len(n['seedAnc'])} inDeg={n['inDeg']} cited={n['cited']} | {n['title'][:70]}")


if __name__ == "__main__":
    sys.exit(main())
