#!/usr/bin/env python3
"""OpenAlex から引用系譜データを取得するスクリプト（v0.2 データ拡張用）

前提:
  - 実行環境のネットワーク許可に api.openalex.org が追加されていること
  - openalex_key.md（Git 管理外・.gitignore 済み）に api_key / mailto があること

取得内容:
  1. 各起点の work レコード（被引用数・著者・掲載誌・abstract・参照 ID リスト）
  2. 起点が参照する全文献のメタデータ（50件ずつバッチ取得）
  3. 各起点を引用する全文献のメタデータ（cursor paging・被引用数付き）

出力: data/openalex/seeds.json / refs.json / citers_<key>.json
使い方:
  python3 fetch_openalex.py --test   # 接続確認（1件だけ取得）
  python3 fetch_openalex.py          # 全件取得
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "data" / "openalex"
API = "https://api.openalex.org"

SEED_DOIS = {
    "whittle1954": "10.1093/biomet/41.3-4.434",
    "gardner1987": "10.1007/BF02275262",
    "keitt2000": "10.1023/A:1008193015770",
    "lindgren2011": "10.1111/j.1467-9868.2011.00777.x",
    "monsi1953": "10.1093/aob/mci052",
    "pacala1996": "10.2307/2963479",
    "canham1990": "10.1139/x90-084",
    "nicotra1999": "10.1890/0012-9658(1999)080[1908:SHOLAW]2.0.CO;2",
}

WORK_FIELDS = ",".join([
    "id", "doi", "title", "publication_year", "cited_by_count",
    "authorships", "primary_location", "referenced_works", "type",
    "abstract_inverted_index",
])
CITER_FIELDS = ",".join([
    "id", "doi", "title", "publication_year", "cited_by_count",
    "referenced_works", "type",
])
# 2ホップ目（参照文献の参照文献）は件数が多いので abstract を省いた軽量フィールド
HOP2_FIELDS = ",".join([
    "id", "doi", "title", "publication_year", "cited_by_count",
    "authorships", "primary_location", "referenced_works", "type",
])
MAX_CITERS_PER_SEED = 10000  # 暴走ガード。超えたら打ち切って truncated を記録
MAX_HOP2_WORKS = 30000       # 2ホップ目の取得上限（超えたら打ち切って truncated を記録）


def load_key():
    """api_key / mailto を取得する。優先順:
    1. openalex_key.md（Git 管理外ファイル）
    2. 環境変数 OPENALEX_API_KEY / OPENALEX_MAILTO（クラウド環境の環境変数に設定可）
    3. どちらも無ければキー無しで実行（OpenAlex は無料・認証不要。
       mailto が無いと polite pool に入らず、レート制限が厳しめになるだけ）
    """
    for p in (HERE / "openalex_key.md",
              HERE.parent / "openalex_key.md"):
        if p.exists():
            text = p.read_text(encoding="utf-8")
            key = re.search(r"api_key:\s*(\S+)", text)
            mail = re.search(r"mailto:\s*(\S+)", text)
            if key:
                return key.group(1), (mail.group(1) if mail else None)
    key = os.environ.get("OPENALEX_API_KEY") or None
    mail = os.environ.get("OPENALEX_MAILTO") or None
    if not key:
        print("注意: API キーが見つかりません。キー無し（無料枠）で実行します。", file=sys.stderr)
    return key, mail


def request(path, params, api_key, mailto, tries=5):
    q = dict(params)
    if mailto:
        q["mailto"] = mailto
    if api_key:
        q["api_key"] = api_key
    url = f"{API}{path}?{urllib.parse.urlencode(q)}"
    req = urllib.request.Request(url, headers={"User-Agent": "citation-genealogy-prototype"})
    delay = 2
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and i < tries - 1:
                wait = int(e.headers.get("Retry-After", delay))
                time.sleep(max(wait, delay)); delay *= 2
                continue
            body = e.read()[:300]
            sys.exit(f"HTTP {e.code} for {path} params={params}: {body}")
        except urllib.error.URLError as e:
            if i < tries - 1:
                time.sleep(delay); delay *= 2
                continue
            sys.exit(f"接続失敗: {e}. ネットワーク許可に api.openalex.org が追加されているか確認してください。")


def reconstruct_abstract(inv):
    if not inv:
        return None
    pos = [(i, w) for w, idxs in inv.items() for i in idxs]
    return " ".join(w for _, w in sorted(pos))[:1500] or None


def slim(work):
    """保存前に abstract_inverted_index を平文へ置き換える。"""
    w = dict(work)
    w["abstract"] = reconstruct_abstract(w.pop("abstract_inverted_index", None))
    return w


def fetch_by_ids(ids, fields, api_key, mailto, label):
    """OpenAlex ID のリストを 50件ずつバッチ取得する。"""
    out = []
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        short = [rid.rsplit("/", 1)[-1] for rid in chunk]
        page = request("/works", {
            "filter": "openalex:" + "|".join(short),
            "select": fields, "per-page": 50,
        }, api_key, mailto)
        out.extend(slim(w) for w in page["results"])
        if (i // 50) % 10 == 0 or i + 50 >= len(ids):
            print(f"{label} {min(i + 50, len(ids))}/{len(ids)}")
        time.sleep(0.15)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="接続確認のみ（Keitt 2000 を1件取得）")
    ap.add_argument("--depth", type=int, choices=(1, 2), default=2,
                    help="後方探索の深さ。1=起点の参照文献まで、2=その参照文献の参照文献まで全網羅（既定）")
    ap.add_argument("--no-citers", action="store_true", help="前方（被引用）の取得を省略")
    args = ap.parse_args()
    api_key, mailto = load_key()
    OUT.mkdir(parents=True, exist_ok=True)

    if args.test:
        w = request(f"/works/doi:{urllib.parse.quote(SEED_DOIS['keitt2000'], safe='')}",
                    {"select": "id,doi,title,publication_year,cited_by_count"}, api_key, mailto)
        print("接続OK:", json.dumps(w, ensure_ascii=False))
        return

    # 1. 起点 work レコード
    seeds = {}
    for key, doi in SEED_DOIS.items():
        w = request(f"/works/doi:{urllib.parse.quote(doi, safe='')}",
                    {"select": WORK_FIELDS}, api_key, mailto)
        seeds[key] = slim(w)
        print(f"seed {key}: {w['id']} cited_by={w['cited_by_count']} refs={len(w['referenced_works'])}")
        time.sleep(0.15)
    (OUT / "seeds.json").write_text(json.dumps(seeds, ensure_ascii=False, indent=1), encoding="utf-8")

    # 2. 参照文献メタデータ（1ホップ目・重複除去して 50件ずつ）
    seed_ids = {s["id"] for s in seeds.values()}
    ref_ids = sorted({rid for s in seeds.values() for rid in s["referenced_works"]} - seed_ids)
    refs = fetch_by_ids(ref_ids, WORK_FIELDS, api_key, mailto, "refs(hop1)")
    (OUT / "refs.json").write_text(json.dumps(refs, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"hop1: {len(refs)} 件")

    # 2b. 2ホップ目: 参照文献がさらに参照している文献をすべて取得（文献の宇宙の幹と枝）
    if args.depth >= 2:
        known = seed_ids | set(ref_ids)
        hop2_ids = sorted({rid for w in refs for rid in w.get("referenced_works", [])} - known)
        truncated = len(hop2_ids) > MAX_HOP2_WORKS
        if truncated:
            print(f"注意: 2ホップ目 {len(hop2_ids)} 件が上限 {MAX_HOP2_WORKS} を超えるため打ち切り")
            hop2_ids = hop2_ids[:MAX_HOP2_WORKS]
        refs2 = fetch_by_ids(hop2_ids, HOP2_FIELDS, api_key, mailto, "refs(hop2)")
        (OUT / "refs_hop2.json").write_text(json.dumps(
            {"truncated": truncated, "requested": len(hop2_ids), "works": refs2},
            ensure_ascii=False), encoding="utf-8")
        print(f"hop2: {len(refs2)} 件 (truncated={truncated})")

    # 3. 各起点の被引用文献（全件・cursor paging）
    for key, s in ({} if args.no_citers else seeds).items():
        wid = s["id"].rsplit("/", 1)[-1]
        citers, cursor, truncated = [], "*", False
        while cursor:
            page = request("/works", {
                "filter": f"cites:{wid}", "select": CITER_FIELDS,
                "per-page": 200, "cursor": cursor,
            }, api_key, mailto)
            citers.extend(slim(w) for w in page["results"])
            cursor = page["meta"].get("next_cursor")
            if len(citers) >= MAX_CITERS_PER_SEED:
                truncated = True
                break
            time.sleep(0.15)
        (OUT / f"citers_{key}.json").write_text(json.dumps(
            {"seed": key, "seed_openalex_id": s["id"], "truncated": truncated, "citers": citers},
            ensure_ascii=False), encoding="utf-8")
        print(f"citers {key}: {len(citers)} 件 (truncated={truncated})")

    print("done. 出力:", OUT)


if __name__ == "__main__":
    main()
