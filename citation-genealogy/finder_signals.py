#!/usr/bin/env python3
"""見落とし候補の信号計算（v0.3・標準ライブラリのみ）

build_data.py から呼ぶ。入力は fetch_crawl.py の出力（辞書化済みの work レコード）。

信号:
  - direct_links   既知文献との直接の引用関係の本数（引用している + 引用されている）
  - cocite         共引用: 既知文献と一緒に引用された回数と、一緒に引用された既知文献の種類数
  - coupling       書誌結合: 既知文献と共有する参照文献の数（Jaccard も返す）
  - semantic       TF-IDF コサイン類似度: 既知文献（タイトル＋要旨）との最大類似度と、
                   クラスタ重心との類似度（どのクラスタに近いか）
  - topic          OpenAlex primary_topic が既知文献のトピック集合に含まれるか
  - related        OpenAlex related_works として既知文献から挙げられたか

TF-IDF は疎ベクトル（dict）で持ち、候補側は既知 40 件＋クラスタ重心（≤ 8）とだけ内積を取るので
3 万文書でも O(文書数 × 平均語数 × 既知件数) に収まる。
"""
import math
import re
from collections import defaultdict, Counter

STOPWORDS = set("""
a an the and or of in on at to for from by with without as is are was were be been being this that these those
it its into than then there their they them we our us you your he she his her not no nor but if so such which who
whom whose what when where why how all any both each few more most other some own same very can will just should
may might must also between among over under during before after above below up down out off again further once
here about against because until while do does did doing have has had having only own too s t via use used using
based results result study studies show shows shown found data model models analysis approach method methods
paper present presented effect effects two three one however within across using new high low large small
significant significantly different differences difference increase increased decrease decreased compared
""".split())
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-]+")


def stem(t):
    """軽い語幹処理（複数形・-ies のみ）。ビューアの query 正規化と同じ規則"""
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 4 and t.endswith("es") and not t.endswith("ss"):
        return t[:-2] if t.endswith(("shes", "ches", "xes", "zes")) else t[:-1]
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def tokens(text):
    """語幹化したトークン列（重複あり・順序保持）"""
    out = []
    for t in TOKEN_RE.findall((text or "").lower()):
        t = t.strip("-")
        if len(t) < 3 or t in STOPWORDS or t.isdigit():
            continue
        out.append(stem(t))
    return out


def short(oa_id):
    return oa_id.rsplit("/", 1)[-1] if oa_id else None


# ---------------------------------------------------------------- TF-IDF
class TfIdf:
    """タイトル（重み 2）＋要旨（重み 1）の TF-IDF。l2 正規化した疎ベクトルを返す"""

    def __init__(self, docs, min_df=2, max_df_ratio=0.3):
        # docs: {id: (title, abstract)}
        self.df = Counter()
        self.tf = {}
        for wid, (title, abstract) in docs.items():
            c = Counter()
            for t in tokens(title):
                c[t] += 2
            for t in tokens(abstract):
                c[t] += 1
            self.tf[wid] = c
            self.df.update(c.keys())
        n = max(1, len(docs))
        max_df = max(min_df, int(max_df_ratio * n))
        self.idf = {t: math.log(1 + n / d) for t, d in self.df.items() if min_df <= d <= max_df}
        self.vec = {wid: self._vector(c) for wid, c in self.tf.items()}

    def _vector(self, counts):
        v = {}
        for t, c in counts.items():
            w = self.idf.get(t)
            if w:
                v[t] = (1 + math.log(c)) * w
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    @staticmethod
    def dot(a, b):
        if len(a) > len(b):
            a, b = b, a
        return sum(x * b.get(t, 0.0) for t, x in a.items())

    @staticmethod
    def centroid(vectors):
        acc = defaultdict(float)
        for v in vectors:
            for t, x in v.items():
                acc[t] += x
        norm = math.sqrt(sum(x * x for x in acc.values())) or 1.0
        return {t: x / norm for t, x in acc.items()}


def semantic_scores(tfidf, seed_ids, seed_cluster):
    """各文書について: 既知文献との最大コサイン（と相手）、クラスタ重心との最大コサイン（と相手）"""
    seed_vecs = {sid: tfidf.vec[sid] for sid in seed_ids if sid in tfidf.vec}
    by_cluster = defaultdict(list)
    for sid, v in seed_vecs.items():
        by_cluster[seed_cluster[sid]].append(v)
    cent = {c: TfIdf.centroid(vs) for c, vs in by_cluster.items()}
    out = {}
    for wid, v in tfidf.vec.items():
        best_s, best_sid = 0.0, None
        for sid, sv in seed_vecs.items():
            if sid == wid:
                continue
            d = TfIdf.dot(v, sv)
            if d > best_s:
                best_s, best_sid = d, sid
        best_c, best_cl = 0.0, None
        for c, cv in cent.items():
            d = TfIdf.dot(v, cv)
            if d > best_c:
                best_c, best_cl = d, c
        out[wid] = {"sim_seed": round(best_s, 3), "sim_seed_id": best_sid,
                    "sim_cluster": round(best_c, 3), "sim_cluster_name": best_cl}
    return out


# ---------------------------------------------------------------- 引用トポロジ
def direct_links(works, seed_ids):
    """{id: {"cites": [seed ids], "cited_by": [seed ids]}} 既知文献との直接関係"""
    seed_set = set(seed_ids)
    links = defaultdict(lambda: {"cites": [], "cited_by": []})
    for wid, w in works.items():
        for r in w.get("referenced_works") or []:
            rs = short(r)
            if rs in seed_set and rs != wid:
                links[wid]["cites"].append(rs)
                if wid in seed_set:
                    pass
            if wid in seed_set and rs in works and rs != wid:
                links[rs]["cited_by"].append(wid)
    return links


def bibliographic_coupling(works, seed_ids):
    """既知文献と共有する参照文献の数（最大の相手と、既知全体の参照集合との共有数・Jaccard）"""
    seed_refs = {sid: {short(r) for r in works[sid].get("referenced_works") or []} for sid in seed_ids if sid in works}
    union = set().union(*seed_refs.values()) if seed_refs else set()
    out = {}
    for wid, w in works.items():
        refs = {short(r) for r in w.get("referenced_works") or []}
        if not refs:
            continue
        shared_union = len(refs & union)
        if not shared_union:
            continue
        best, best_sid = 0, None
        for sid, sr in seed_refs.items():
            if sid == wid or not sr:
                continue
            n = len(refs & sr)
            if n > best:
                best, best_sid = n, sid
        out[wid] = {"coupling": shared_union, "coupling_jaccard": round(shared_union / len(refs | union), 4),
                    "coupling_best": best, "coupling_best_id": best_sid}
    return out


def topic_match(works, seed_ids):
    """既知文献のトピック集合（primary_topic と topics）に primary_topic が含まれるか"""
    seed_topics = set()
    for sid in seed_ids:
        s = works.get(sid) or {}
        pt = s.get("primary_topic") or {}
        if pt.get("id"):
            seed_topics.add(pt["id"])
        for t in s.get("topics") or []:
            if t.get("id"):
                seed_topics.add(t["id"])
    out = {}
    for wid, w in works.items():
        pt = w.get("primary_topic") or {}
        out[wid] = bool(pt.get("id") and pt["id"] in seed_topics)
    return out, seed_topics
