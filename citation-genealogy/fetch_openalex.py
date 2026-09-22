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

料金体系の注意（2026-09 時点）:
  - 単一レコード取得 /works/W... は無料（予算消費ゼロ）。
  - 一覧クエリ /works?filter=... は 1 リクエスト 1 クレジット。キー無しだと
    「送信元 IP ごとの無料日次予算」から引かれるため、共有 IP の環境では
    すぐ枯渇する。枯渇時は後方探索を単一レコード取得（並列）へ自動で
    切り替え、前方（被引用）取得は cites: フィルタ＝一覧クエリが必須なので
    打ち切って fetch_status.json に記録する。
"""
import concurrent.futures
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
    "authorships", "primary_location", "referenced_works", "type",
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


class BudgetExhausted(Exception):
    """キー無し・共有 IP の無料日次予算が尽きた（一覧クエリのみ影響）"""


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
            if e.code == 429 and e.headers.get("x-ratelimit-remaining-usd") == "0" \
                    and e.headers.get("x-ratelimit-cost-required-usd") not in (None, "0"):
                raise BudgetExhausted(e.read()[:300].decode("utf-8", "replace"))
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
    """保存前に abstract_inverted_index を平文へ置き換え、著者・掲載誌を必要最小限に縮める
    （所属機関などを落とす。2ホップで数千件になるためファイルサイズ対策）。"""
    w = dict(work)
    if "abstract_inverted_index" in w or "abstract" not in w:
        w["abstract"] = reconstruct_abstract(w.pop("abstract_inverted_index", None))
    if "authorships" in w:
        w["authorships"] = [{"author": {"display_name": (a.get("author") or {}).get("display_name")}}
                            for a in (w.get("authorships") or [])]
    if "primary_location" in w:
        loc = w.get("primary_location") or {}
        src = loc.get("source") or {}
        w["primary_location"] = {"source": {"display_name": src.get("display_name")} if src else None,
                                 "raw_source_name": loc.get("raw_source_name")}
    return w


MODE = {"single": False}   # True になると以降は単一レコード取得のみ使う
WORKERS = 8                # 単一取得の並列数（公式目安 10 req/s を超えない）


def fetch_one(wid, fields, api_key, mailto):
    """単一レコード取得（無料）。存在しない ID は None。"""
    try:
        return slim(request(f"/works/{wid}", {"select": fields}, api_key, mailto))
    except SystemExit as e:
        if "HTTP 404" in str(e):
            return None
        raise


def fetch_by_ids(ids, fields, api_key, mailto, label):
    """OpenAlex ID のリストを取得する。
    既定は 50件ずつのバッチ（一覧クエリ・1クレジット/回）。予算切れを検知したら
    単一レコード取得（無料）を並列で回す方式に切り替える。"""
    out = []
    i = 0
    while i < len(ids) and not MODE["single"]:
        chunk = ids[i:i + 50]
        short = [rid.rsplit("/", 1)[-1] for rid in chunk]
        try:
            page = request("/works", {
                "filter": "openalex:" + "|".join(short),
                "select": fields, "per-page": 50,
            }, api_key, mailto)
        except BudgetExhausted:
            print(f"{label}: 一覧クエリの無料予算が枯渇。単一レコード取得（並列 {WORKERS}）へ切替",
                  file=sys.stderr)
            MODE["single"] = True
            break
        out.extend(slim(w) for w in page["results"])
        i += 50
        if (i // 50) % 10 == 0 or i >= len(ids):
            print(f"{label} {min(i, len(ids))}/{len(ids)}")
        time.sleep(0.15)
    if i < len(ids):
        rest = [rid.rsplit("/", 1)[-1] for rid in ids[i:]]
        done = 0
        with concurrent.futures.ThreadPoolExecutor(WORKERS) as ex:
            for w in ex.map(lambda wid: fetch_one(wid, fields, api_key, mailto), rest):
                if w is not None:
                    out.append(w)
                done += 1
                if done % 500 == 0 or done == len(rest):
                    print(f"{label} {i + done}/{len(ids)} (single)", flush=True)
    return out


def fetch_abstracts(api_key, mailto):
    """refs_hop2.json / citers_*.json の文献のうち要旨未取得のものを取得して abstracts.json に保存。
    要旨はビューアに埋め込まず、キーワード関連度の索引（build_data.py）だけに使う。"""
    have = {}
    out_path = OUT / "abstracts.json"
    if out_path.exists():
        have = json.loads(out_path.read_text(encoding="utf-8"))
    ids = []
    hop2 = json.loads((OUT / "refs_hop2.json").read_text(encoding="utf-8"))
    ids += [w["id"] for w in hop2["works"]]
    for p in sorted(OUT.glob("citers_*.json")):
        ids += [w["id"] for w in json.loads(p.read_text(encoding="utf-8"))["citers"]]
    ids = sorted({i for i in ids if i.rsplit("/", 1)[-1] not in have})
    print(f"abstracts: 取得対象 {len(ids)} 件（取得済 {len(have)} 件）")
    works = fetch_by_ids(ids, "id,abstract_inverted_index", api_key, mailto, "abstracts")
    got = 0
    for w in works:
        wid = w["id"].rsplit("/", 1)[-1]
        have[wid] = w.get("abstract")   # None も記録（OpenAlex に要旨が無い＝再取得不要）
        if w.get("abstract"):
            got += 1
    out_path.write_text(json.dumps(have, ensure_ascii=False), encoding="utf-8")
    print(f"abstracts: 要旨あり {got} / {len(works)} 件 → {out_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="接続確認のみ（Keitt 2000 を1件取得）")
    ap.add_argument("--depth", type=int, choices=(1, 2), default=2,
                    help="後方探索の深さ。1=起点の参照文献まで、2=その参照文献の参照文献まで全網羅（既定）")
    ap.add_argument("--no-citers", action="store_true", help="前方（被引用）の取得を省略")
    ap.add_argument("--refresh", action="store_true", help="既存の seeds.json を無視して再取得")
    ap.add_argument("--citers-only", action="store_true",
                    help="後方（refs.json / refs_hop2.json）は既存ファイルを使い、前方（被引用）だけ取得する")
    ap.add_argument("--abstracts", action="store_true",
                    help="既存の 2ホップ層・後続層の文献について要旨だけ取得し abstracts.json に保存する")
    args = ap.parse_args()
    api_key, mailto = load_key()
    OUT.mkdir(parents=True, exist_ok=True)

    if args.abstracts:
        fetch_abstracts(api_key, mailto)
        return

    if args.test:
        w = request(f"/works/doi:{urllib.parse.quote(SEED_DOIS['keitt2000'], safe='')}",
                    {"select": "id,doi,title,publication_year,cited_by_count"}, api_key, mailto)
        print("接続OK:", json.dumps(w, ensure_ascii=False))
        return

    # 1. 起点 work レコード
    seeds = {}
    if (OUT / "seeds.json").exists() and not args.refresh:
        seeds = json.loads((OUT / "seeds.json").read_text(encoding="utf-8"))
        print("seeds.json を再利用（--refresh で再取得）")
    for key, doi in SEED_DOIS.items():
        if key in seeds:
            continue
        w = request(f"/works/doi:{urllib.parse.quote(doi, safe='')}",
                    {"select": WORK_FIELDS}, api_key, mailto)
        seeds[key] = slim(w)
        print(f"seed {key}: {w['id']} cited_by={w['cited_by_count']} refs={len(w['referenced_works'])}")
        time.sleep(0.15)
    (OUT / "seeds.json").write_text(json.dumps(seeds, ensure_ascii=False, indent=1), encoding="utf-8")

    # 2. 参照文献メタデータ（1ホップ目・重複除去して 50件ずつ）
    seed_ids = {s["id"] for s in seeds.values()}
    ref_ids = sorted({rid for s in seeds.values() for rid in s["referenced_works"]} - seed_ids)
    if args.citers_only and (OUT / "refs.json").exists():
        print("--citers-only: 後方データは既存ファイルを再利用")
        refs = []
    else:
        refs = fetch_by_ids(ref_ids, WORK_FIELDS, api_key, mailto, "refs(hop1)")
        (OUT / "refs.json").write_text(json.dumps(refs, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"hop1: {len(refs)} 件")

    # 2b. 2ホップ目: 参照文献がさらに参照している文献をすべて取得（文献の宇宙の幹と枝）
    if args.depth >= 2 and not args.citers_only:
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

    # 3. 各起点の被引用文献（全件・cursor paging）。cites: フィルタは一覧クエリ
    #    なので予算切れなら打ち切り、状態を fetch_status.json に残す。
    prev = {}
    if (OUT / "fetch_status.json").exists():
        prev = json.loads((OUT / "fetch_status.json").read_text(encoding="utf-8"))
    status = {"backward_mode": prev.get("backward_mode") if args.citers_only else ("single" if MODE["single"] else "batch"),
              "citers": {}, "citers_skipped_reason": None}
    for key, s in ({} if args.no_citers else seeds).items():
        wid = s["id"].rsplit("/", 1)[-1]
        citers, cursor, truncated = [], "*", False
        try:
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
        except BudgetExhausted as e:
            status["citers_skipped_reason"] = (
                "cites: フィルタ（一覧クエリ）の無料予算が枯渇。API キーを openalex_key.md に置くか、"
                "UTC 深夜のリセット後に再実行してください。")
            print("citers: 予算枯渇のため打ち切り:", str(e)[:200], file=sys.stderr)
            break
        (OUT / f"citers_{key}.json").write_text(json.dumps(
            {"seed": key, "seed_openalex_id": s["id"], "truncated": truncated, "citers": citers},
            ensure_ascii=False), encoding="utf-8")
        status["citers"][key] = {"count": len(citers), "truncated": truncated}
        print(f"citers {key}: {len(citers)} 件 (truncated={truncated})")
    (OUT / "fetch_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")

    print("done. 出力:", OUT)


if __name__ == "__main__":
    main()
