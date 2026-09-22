#!/usr/bin/env python3
"""既知リスト（data/known_list.csv）を起点に OpenAlex をクロールする（v0.3 見落とし検出用）

取得内容（すべて data/crawl/ に保存）:
  1. seeds.json     既知リストの work レコード（参照リスト・関連文献・トピック付き）
  2. refs.json      既知文献が参照する文献（1ホップ後方・要旨付き）
  3. citers.json    既知文献を引用する文献（1ホップ前方・要旨・参照リスト付き・重複除去）
  4. cocite_stats.json  citers の参照リストから数えた共引用統計
                    {work_id: [共引用回数, 一緒に引用された既知文献の種類数]}
  5. cocited.json   共引用で候補に上がった文献の本体（既知 2 件以上と共引用されたもの、上限あり）
  6. related.json   OpenAlex が各既知文献の related_works として返す文献の本体（意味ベースの保険）
  7. status.json    件数・打ち切りの記録

使い方:
  python3 fetch_crawl.py                # 全件
  python3 fetch_crawl.py --list other.csv --out data/crawl_other
キーは openalex_key.md（api_key: / mailto:）から読む。無ければキー無しで動くが
一覧クエリの無料予算（送信元 IP 単位）はすぐ尽きるのでキー推奨。
"""
import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
API = "https://api.openalex.org"

BASE_FIELDS = [
    "id", "doi", "title", "publication_year", "cited_by_count",
    "authorships", "primary_location", "referenced_works", "type",
    "abstract_inverted_index", "primary_topic",
]
SEED_FIELDS = ",".join(BASE_FIELDS + ["related_works", "topics"])
WORK_FIELDS = ",".join(BASE_FIELDS)
MAX_CITERS_PER_SEED = 10000
MAX_COCITED = 6000          # 共引用候補の本体取得上限
MIN_COCITE_DISTINCT = 2     # 既知文献の何種類と一緒に引用されていれば候補にするか


def load_key():
    for p in (HERE / "openalex_key.md", HERE.parent / "openalex_key.md"):
        if p.exists():
            text = p.read_text(encoding="utf-8")
            key = re.search(r"api_key:\s*(\S+)", text)
            mail = re.search(r"mailto:\s*(\S+)", text)
            if key:
                return key.group(1), (mail.group(1) if mail else None)
    print("注意: API キーが見つかりません。キー無しで実行します。", file=sys.stderr)
    return None, None


def request(path, params, api_key, mailto, tries=6):
    q = dict(params)
    if mailto:
        q["mailto"] = mailto
    if api_key:
        q["api_key"] = api_key
    url = f"{API}{path}?{urllib.parse.urlencode(q)}"
    req = urllib.request.Request(url, headers={"User-Agent": "citation-genealogy-crawler"})
    delay = 2
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (429, 500, 502, 503, 504) and i < tries - 1:
                wait = e.headers.get("Retry-After")
                time.sleep(min(60, max(int(wait) if wait and wait.isdigit() else 0, delay)))
                delay *= 2
                continue
            body = e.read()[:300]
            sys.exit(f"HTTP {e.code} for {path} params={params}: {body}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if i < tries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            sys.exit(f"接続失敗: {e}")


def reconstruct_abstract(inv):
    if not inv:
        return None
    pos = [(i, w) for w, idxs in inv.items() for i in idxs]
    return " ".join(w for _, w in sorted(pos))[:2000] or None


def slim(work):
    """保存前に要旨を平文へ、著者・掲載誌・トピックを必要最小限に縮める"""
    w = dict(work)
    w["abstract"] = reconstruct_abstract(w.pop("abstract_inverted_index", None))
    w["authorships"] = [{"author": {"display_name": (a.get("author") or {}).get("display_name")}}
                        for a in (w.get("authorships") or [])]
    loc = w.get("primary_location") or {}
    src = loc.get("source") or {}
    w["primary_location"] = {"source": {"display_name": src.get("display_name")} if src else None,
                             "raw_source_name": loc.get("raw_source_name")}
    pt = w.get("primary_topic") or None
    if pt:
        w["primary_topic"] = {"id": pt.get("id"), "display_name": pt.get("display_name"),
                              "subfield": (pt.get("subfield") or {}).get("display_name"),
                              "field": (pt.get("field") or {}).get("display_name")}
    if "topics" in w:
        w["topics"] = [{"id": t.get("id"), "display_name": t.get("display_name"), "score": t.get("score")}
                       for t in (w.get("topics") or [])]
    return w


def short(oa_id):
    return oa_id.rsplit("/", 1)[-1]


def fetch_by_ids(ids, fields, api_key, mailto, label):
    out = []
    for i in range(0, len(ids), 50):
        chunk = [short(x) for x in ids[i:i + 50]]
        page = request("/works", {"filter": "openalex:" + "|".join(chunk),
                                  "select": fields, "per-page": 50}, api_key, mailto)
        if page:
            out.extend(slim(w) for w in page["results"])
        if (i // 50) % 20 == 0 or i + 50 >= len(ids):
            print(f"{label} {min(i + 50, len(ids))}/{len(ids)}", flush=True)
        time.sleep(0.1)
    return out


def make_key(note, used):
    m = re.search(r"(\d{4})", note)
    year = m.group(1) if m else "0000"
    first = re.sub(r"[^a-z]", "", note.split()[0].lower()) or "work"
    key = first + year
    n = 2
    while key in used:
        key = f"{first}{year}_{n}"
        n += 1
    used.add(key)
    return key


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", default=str(HERE / "data" / "known_list.csv"))
    ap.add_argument("--out", default=str(HERE / "data" / "crawl"))
    ap.add_argument("--no-citers", action="store_true")
    args = ap.parse_args()
    api_key, mailto = load_key()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    status = {"list": args.list, "seeds": {}, "truncated_citers": [], "missing_seeds": []}

    # 1. 既知リスト
    rows = list(csv.DictReader(open(args.list, encoding="utf-8")))
    used = set()
    seeds = {}
    for r in rows:
        key = make_key(r["note"], used)
        w = request(f"/works/doi:{urllib.parse.quote(r['doi'].strip(), safe='')}",
                    {"select": SEED_FIELDS}, api_key, mailto)
        if not w:
            status["missing_seeds"].append({"key": key, "doi": r["doi"], "note": r["note"]})
            print(f"MISSING seed {key} {r['doi']}", file=sys.stderr)
            continue
        w = slim(w)
        w.update({"key": key, "cluster": r["cluster"].strip(), "phase": int(r["phase"]), "note": r["note"].strip(),
                  "input_doi": r["doi"].strip()})
        seeds[key] = w
        print(f"seed {key:<20} {w['publication_year']} cited={w['cited_by_count']:>6} refs={len(w['referenced_works'])}")
        time.sleep(0.1)
    (out / "seeds.json").write_text(json.dumps(seeds, ensure_ascii=False, indent=1), encoding="utf-8")
    seed_ids = {short(s["id"]): k for k, s in seeds.items()}

    # 2. 参照文献（1ホップ後方）
    ref_ids = sorted({r for s in seeds.values() for r in s["referenced_works"]} - {s["id"] for s in seeds.values()})
    refs = fetch_by_ids(ref_ids, WORK_FIELDS, api_key, mailto, "refs")
    (out / "refs.json").write_text(json.dumps(refs, ensure_ascii=False), encoding="utf-8")
    print(f"refs: {len(refs)} 件（要求 {len(ref_ids)}）")
    status["refs"] = {"requested": len(ref_ids), "fetched": len(refs)}

    # 3. 被引用文献（1ホップ前方・全起点・重複除去）
    citers = {}
    if not args.no_citers:
        for key, s in seeds.items():
            wid = short(s["id"])
            cursor, n, truncated = "*", 0, False
            while cursor:
                page = request("/works", {"filter": f"cites:{wid}", "select": WORK_FIELDS,
                                          "per-page": 200, "cursor": cursor}, api_key, mailto)
                if not page:
                    break
                for w in page["results"]:
                    citers.setdefault(short(w["id"]), slim(w))
                    n += 1
                cursor = page["meta"].get("next_cursor")
                if n >= MAX_CITERS_PER_SEED:
                    truncated = True
                    break
                time.sleep(0.1)
            status["seeds"][key] = {"citers": n, "truncated": truncated}
            if truncated:
                status["truncated_citers"].append(key)
            print(f"citers {key:<20} {n} 件{' (打ち切り)' if truncated else ''}  累計 {len(citers)}", flush=True)
    (out / "citers.json").write_text(json.dumps(list(citers.values()), ensure_ascii=False), encoding="utf-8")
    print(f"citers: {len(citers)} 件（重複除去後）")

    # 4. 共引用統計: 各 citer が既知文献と一緒に引用している文献を数える
    known_ids = set(seed_ids)
    fetched_ids = known_ids | {short(w["id"]) for w in refs} | set(citers)
    cocite = defaultdict(int)
    distinct = defaultdict(set)
    for c in citers.values():
        refs_c = [short(r) for r in c.get("referenced_works") or []]
        known_in = [r for r in refs_c if r in known_ids]
        if not known_in:
            continue
        for r in refs_c:
            if r in known_ids:
                continue
            cocite[r] += 1
            distinct[r].update(known_in)
    stats = {r: [cocite[r], len(distinct[r])] for r in cocite if cocite[r] >= 2 or len(distinct[r]) >= 2}
    (out / "cocite_stats.json").write_text(json.dumps(stats), encoding="utf-8")
    print(f"cocite: {len(cocite)} 種類の文献が既知文献と共引用、うち統計保存 {len(stats)} 件")

    # 5. 共引用候補の本体（既知 MIN_COCITE_DISTINCT 種類以上と共引用、未取得のもの、回数順に上限まで）
    cand = [r for r, (n, d) in stats.items() if d >= MIN_COCITE_DISTINCT and r not in fetched_ids]
    cand.sort(key=lambda r: (-stats[r][1], -stats[r][0]))
    status["cocited"] = {"eligible": len(cand), "fetched": min(len(cand), MAX_COCITED),
                         "truncated": len(cand) > MAX_COCITED}
    cand = cand[:MAX_COCITED]
    cocited = fetch_by_ids(["https://openalex.org/" + r for r in cand], WORK_FIELDS, api_key, mailto, "cocited")
    (out / "cocited.json").write_text(json.dumps(cocited, ensure_ascii=False), encoding="utf-8")
    print(f"cocited: {len(cocited)} 件取得（候補 {len(cand)} 件、打ち切り={status['cocited']['truncated']}）")
    fetched_ids |= {short(w["id"]) for w in cocited}

    # 6. OpenAlex の related_works（意味ベースの保険）
    rel_ids = sorted({short(r) for s in seeds.values() for r in s.get("related_works") or []} - fetched_ids)
    related = fetch_by_ids(["https://openalex.org/" + r for r in rel_ids], WORK_FIELDS, api_key, mailto, "related")
    (out / "related.json").write_text(json.dumps(related, ensure_ascii=False), encoding="utf-8")
    status["related"] = {"requested": len(rel_ids), "fetched": len(related)}
    print(f"related: {len(related)} 件")

    (out / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done:", out)


if __name__ == "__main__":
    main()
