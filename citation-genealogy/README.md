# 引用地層図 — 引用系譜ビューア 試作 v0.1

複数の学術論文を起点に、引用・被引用関係を「上=新しい・下=古い」の時間軸で
眺めるためのプロトタイプ。キーワードや意味類似ではなく、**確認できた実際の
引用関係のみ**をネットワークの骨格とする。

- ビューア本体: `index.html`（自己完結・データ埋め込み済み。ブラウザで開くだけで動く）
- GitHub Pages: `https://<user>.github.io/Claude-public/citation-genealogy/`

## 起点文献（8件）

| 系譜 | 文献 | DOI |
|---|---|---|
| A 確率場・中立景観 | Whittle 1954 | 10.1093/biomet/41.3-4.434 |
| A | Gardner et al. 1987 | 10.1007/BF02275262 |
| A | Keitt 2000 | 10.1023/A:1008193015770 |
| A | Lindgren et al. 2011 | 10.1111/j.1467-9868.2011.00777.x |
| B 森林・林冠光環境 | Monsi & Saeki 1953/2005 | 10.1093/aob/mci052 |
| B | Canham et al. 1990 | 10.1139/x90-084 |
| B | Pacala et al. 1996 | 10.2307/2963479 |
| B | Nicotra et al. 1999 | 10.1890/0012-9658(1999)080[1908:SHOLAW]2.0.CO;2 |

## データの由来と範囲（2026-09-22 取得）

データソースは **Scite の citation_graph API（MCP 経由）**。この実行環境の
ネットワークポリシーでは OpenAlex / Semantic Scholar / Crossref /
OpenCitations への直接アクセスが遮断されており、かつ Scite の無料枠・
Consensus の無料枠は取得中に使い切ったため、v0.1 は以下の2回分の取得結果で
構成されている。

1. `data/backward_scite.json` — 8起点すべての参照文献（後方1ホップ、
   DOI 解決分は**打ち切りなし**で全件、443辺）
2. `data/forward_keitt_scite.json` — Keitt 2000 の被引用 60件
   （**打ち切りありのサンプル**。他の7起点の前方は未取得）

既知の限界:

- scite は DOI に解決できた引用関係のみを返す。古い文献ほど参照リストが
  過少（例: Whittle 1954 は 6件のみ）。なお scite が報告する起点ごとの
  参照数（seed_coverage）は4起点で実際に返された辺数と1件ずれており、
  表示は実辺数に統一している。
- 全世界の被引用数は未取得。ノードの大きさは「この図の中で参照されている数」。
- 未探索（参照リストを取得していない）と引用なしは別物として扱い、
  各ノードの `explored` フィールドと詳細パネルで区別している。

## 初期成果（引用関係の事実として確認できたこと）

- 起点間の直接引用: Keitt 2000 → Gardner 1987、Lindgren 2011 → Whittle 1954、
  Nicotra 1999 → Pacala 1996、Pacala 1996 → Canham 1990
- 2起点以上に共有される祖先: 13件
- **両系譜をまたぐ祖先（ブリッジ）: 1件** — Bradshaw & Spies 1992
  “Characterizing Canopy Gap Structure in Forests Using Wavelet Analysis”
  (10.2307/2261007) が Keitt 2000（系譜A）と Nicotra 1999（系譜B）の両方から
  引用されている。

## ファイル構成

```
citation-genealogy/
├── README.md
├── build_data.py        # raw → graph.json / index.html / artifact.html 生成
├── template.html        # ビューア本体（__GRAPH_DATA__ にデータを埋め込む）
├── index.html           # 生成物（GitHub Pages 用・完全な HTML 文書）
├── artifact.html        # 生成物（claude.ai Artifact 公開用フラグメント）
└── data/
    ├── backward_scite.json       # raw: 8起点の参照文献
    ├── forward_keitt_scite.json  # raw: Keitt 2000 の被引用サンプル
    └── graph.json                # 整形済みグラフデータ
```

再生成: `python3 build_data.py`（依存なし・標準ライブラリのみ）

## OpenAlex API キーの引き継ぎ

被引用数・著者・abstract・前方探索の拡張（v0.2）は OpenAlex API を使う。

- キーは `citation-genealogy/openalex_key.md` に置く（**Git 管理外**。
  ルートの `.gitignore` で除外済み。コミット禁止）。
- 書式は次の2行を含めばよい: `api_key: <キー>` / `mailto: <メールアドレス>`
- セッションのコンテナは使い捨てなので、新しいセッションでは
  キーファイルを再アップロードして同じ場所に置き直す。
- 取得は `python3 fetch_openalex.py --test`（接続確認）→
  `python3 fetch_openalex.py`（全件取得、`data/openalex/` に保存）。
- **注意**: キーだけでは足りない。実行環境のネットワーク許可に
  `api.openalex.org` が追加されている必要がある（claude.ai/code の
  環境設定 → ネットワークアクセス）。

## 次に決めること（ユーザーと相談）

- 全世界の被引用数・著者・abstract の取得経路
  （本命: 実行環境のネットワーク許可に `api.openalex.org` を追加）
- 前方（被引用）探索の範囲と後続文献の選定基準
- 再帰探索の深さ（現状は後方1ホップ）
- 表示面の改善点（ラベル密度・レイアウト・操作系）
