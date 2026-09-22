# 引用地層図 — 引用系譜ビューア 試作 v0.2

複数の学術論文を起点に、引用・被引用関係を「上=新しい・下=古い」の時間軸で
眺めるためのプロトタイプ。キーワードや意味類似ではなく、**確認できた実際の
引用関係のみ**をネットワークの骨格とする。

- ビューア本体: `index.html`（自己完結・データ埋め込み済み。ブラウザで開くだけで動く）
- GitHub Pages: `https://<user>.github.io/Claude-public/citation-genealogy/`
- 公開済み Artifact: https://claude.ai/artifact/44wTSdKhvzR7bEBL8VvEFz

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

## データの由来と範囲（v0.2, 2026-09-22 OpenAlex 取得）

データソースは **OpenAlex API**（`fetch_openalex.py`）。取得内容:

| 層 | 内容 | 件数 |
|---|---|---|
| 起点 | 8件の work レコード（被引用数・著者・掲載誌・要旨・参照リスト） | 8 |
| 1ホップ | 起点が参照する文献（要旨付き・参照リスト付き）。打ち切りなし | 421 |
| 2ホップ | 1ホップ文献が参照する文献（参照リスト付き・要旨なし）。打ち切りなし。要求 7,933 件のうち OpenAlex 側で消えた ID を除く | 7,569 |
| 後続 | 起点を引用する文献。**OpenAlex 分は未取得**（下記）。暫定で v0.1 の Scite サンプル（Keitt 2000 の被引用 60 件）を表示 | 60 |

合計 8,058 文献・49,809 引用辺（取得済みノード集合の中で参照リストが示す辺すべて。
2ホップ層どうしの引用も含む）。

### OpenAlex の料金体系と取得時の制約

- 単一レコード取得（`/works/W...`）は無料（予算消費ゼロ）。
- 一覧クエリ（`/works?filter=...`）は 1 リクエスト 1 クレジット。**キー無しだと
  送信元 IP ごとの無料日次予算**から引かれるため、共有 IP のクラウド環境では
  すぐ枯渇する（今回は起点 8 件を取った時点で残高ゼロだった）。
- そこで後方 2 ホップは単一レコード取得を 8 並列で回して取り切った
  （`fetch_status.json` の `backward_mode: single`）。
- 前方（被引用）は `cites:` フィルタ＝一覧クエリが必須なので打ち切り。
  **無料の API キーを `openalex_key.md` に置いて再実行すれば全件入る**
  （各起点 142〜2,806 件、合計 8,500 件程度・一覧 45 リクエストほど）。
  Scite MCP も月間上限に達しており代替にならなかった。

### 系譜の判定と主な結果（引用関係の事実として確認できたこと）

- 系譜 A/B の分類は「各起点から引用を **2ホップ以内**でたどって到達できるか」
  （他の起点で経路は止める）による機械的分類。無制限にたどると 2ホップ層どうしの
  引用でつながり 8,058 件中 4,984 件が「両系譜」になって意味を失うため、
  取得範囲と同じ深さで区切った。
- **両系譜の起点が直接引用する祖先（直接ブリッジ）: 1件のまま** — Bradshaw & Spies 1992
  (10.2307/2261007)。Keitt 2000 と Nicotra 1999 が引用。
- **2ホップ以内で両系譜から到達できる祖先: 264件**（v0.1 では見えなかった層）。
  到達する起点数が多い順に: Watt 1947 “Pattern and Process in the Plant Community”
  (5起点)、Pickett & White 1985 “The Ecology of Natural Disturbance and Patch
  Dynamics” (5起点・Gardner が直接引用)、White 1979 “Pattern, process, and natural
  disturbance in vegetation” (5起点)、Harper 1977 “Population Biology of Plants”
  (4起点・図内被引用 152)、Ripley 1981 “Spatial Statistics” (4起点・図内 128)、
  Cressie 1991 “Statistics for Spatial Data” (3起点・図内 268・Keitt/Lindgren が直接引用)。
- 2起点以上が直接引用する共通祖先: 13件（v0.1 と同数）。2ホップ以内で2起点以上から
  到達する文献: 647件。
- これらは引用関係の事実であり、「内容上の系譜が同じ」という解釈とは別。

既知の限界:

- 辺は OpenAlex が解決した参照関係のみ。古い文献ほど参照リストが過少（Whittle 1954 は 9件、
  Monsi & Saeki は 10件）。辺が無いことは「引用なし」を意味しない。
- 2ホップ層は参照リストの ID だけ既知で、その先の文献は取得していない
  （図内にある文献への辺だけ描く）。詳細パネルの「探索状態」で区別している。
- 世界全体の被引用数（`cited_by_count`）はノードの濃さに使うが、質や関連性の指標ではない。

### v0.1 からの変更（比較用に `data/*_scite.json` は残置）

v0.1 は Scite の citation_graph（後方1ホップ・494文献・503辺）。OpenAlex の 1ホップは
421件で Scite の 443辺より少し少ないが、OpenAlex は DOI の無い文献（32件）も
含み、参照リスト付きなので 2ホップへ展開できる。

## ファイル構成

```
citation-genealogy/
├── README.md
├── fetch_openalex.py    # OpenAlex から起点・1ホップ・2ホップ・被引用を取得
├── build_data.py        # raw → graph.json / index.html / artifact.html 生成（レイアウト込み）
├── template.html        # ビューア本体（Canvas 描画。__GRAPH_DATA__ にデータを埋め込む）
├── index.html           # 生成物（GitHub Pages 用・完全な HTML 文書、約 4.7 MB）
├── artifact.html        # 生成物（claude.ai Artifact 公開用フラグメント）
└── data/
    ├── openalex/
    │   ├── seeds.json          # 起点 8 件
    │   ├── refs.json           # 1ホップ（要旨付き）
    │   ├── refs_hop2.json      # 2ホップ（約 9 MB）
    │   ├── fetch_status.json   # 取得モードと前方取得の打ち切り理由
    │   └── citers_<key>.json   # 前方（キー取得後に生成される）
    ├── backward_scite.json       # v0.1 raw（比較用）
    ├── forward_keitt_scite.json  # v0.1 raw（暫定の後続層に使用）
    └── graph.json                # 整形済みグラフデータ（レイアウト座標込み）
```

再生成: `python3 fetch_openalex.py` → `python3 build_data.py`（依存なし・標準ライブラリのみ）

## ビューアの見方（v0.2）

- **縦軸＝年**（上が新しい）。10年ごとの地層帯。横軸は系譜の目安（左＝A 確率場・
  中立景観、右＝B 森林・光環境、中央＝両方から到達）で、正確な意味は持たない。
- **色**: 青＝A の祖先、アクア緑＝B の祖先、橙のひし形＝両系譜から到達（ブリッジ）、
  輪郭のみ＝後続（起点を引用する側）。
- **濃さ＝世界全体の被引用数**（対数）。**大きさ＝この図の中で引用されている数**（幹の太さ）。
  多くの経路が通る高被引用の祖先は濃く大きく、枝先は薄く小さい。辺も幹へ向かうものほど濃い。
- **クリック**で詳細パネル（DOI/OpenAlex リンク、要旨、探索状態、図内の引用・被引用リスト）と、
  祖先・子孫のハイライト。既定は 2 ホップまで（「ハイライト深さ」で 1/2/3/無制限）。
- **キーワード欄**: 未入力時はすべて等価値。入力するとタイトル・要旨・掲載誌との一致度で
  関連文献だけが浮かび（他は薄く）、右パネルに関連度順のリストが出る。要旨は起点と
  1ホップのみ取得済なので、2ホップ層はタイトル一致だけで拾う。
- **絞り込み**: 2ホップ層・後続層の表示切替、共通祖先のみ（2起点以上から到達）、
  枝の刈り込み（図内被引用数の下限）。

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

## v0.2 の仕様（2026-09-22 ユーザーと決定済み・実装済み）

1. **データ経路**: OpenAlex（`fetch_openalex.py`）。キーは任意だが、前方（被引用）の
   全件取得にはキーが実質必須（上記の料金体系）。
2. **前方（被引用）の見せ方**: 被引用数の多さは**ノードの濃さ**。
   「複数の起点・系譜を引用する文献」はキーワード未入力時は特別扱いせず等価値。
   キーワード入力時は関連する論文を優先表示（関連度で強調・絞り込み）。
3. **後方の探索深さ**: **2ホップ全網羅**（実施済み・打ち切りなし）。
4. **表示面**: Canvas 描画（辺・ノード）＋ quadtree ヒットテストに移行。幹を濃く、枝を薄く。

## 引き継ぎメモ（次のセッション向け）

- ブランチ `claude/citation-genealogy-viewer-5tuoep`、PR #1（draft）。
  **新しい PR は作らず #1 に積む**。
- 公開済み Artifact: https://claude.ai/artifact/44wTSdKhvzR7bEBL8VvEFz
  （更新時は `url` にこれを渡して同じリンクを維持する）
- 前方（被引用）を入れるには: OpenAlex の無料キーを `openalex_key.md` に置き
  `python3 fetch_openalex.py`（seeds.json は再利用される）→ `python3 build_data.py`
  → `artifact.html` を再公開。`build_data.py` は `citers_*.json` があれば
  Scite サンプルの代わりにそれを後続層に使う。
- v0.1 の Scite データ（`data/*_scite.json`）は比較用に残す。
