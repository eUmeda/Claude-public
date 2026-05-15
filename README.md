# Claude - Research & Education Projects

研究、教育、プロジェクト開発に関連するWebアプリケーション・インタラクティブデモを集約したサイトです。

> **制作**: このリポジトリのREADME構成は [GitHub Copilot](https://github.com/features/copilot)（AI Chat機能）を活用して構築されています。

---

## 🔬 プロジェクト一覧

### 📊 Strogatz 非線形力学系 - インタラクティブデモ
**「Nonlinear Dynamics and Chaos」による力学系シミュレーション**

Steven Strogatzの教科書を基にしたインタラクティブな動力学デモンストレーション。

**[チートシート（総まとめ）](./strogatz-cheatsheet.html)** - 1D/2D力学系、分岐一覧、重要定理

**[力学系解析チュートリアル](./dynamical-systems-analysis.html)** - ヤコビアン→固有値→安定性分類の王道ワークフロー

#### 8章：2次元系の分岐

| デモ | 内容 | Strogatz節 |
|-----|------|-----------|
| **[結合振動子と準周期性](./Strogatz-8.6-demo.html)** | トーラス上の流れ、位相ロック | 8.6 |
| **[ポアンカレ写像](./strogatz-8-7-demo.html)** | 連続系→離散系、クモの巣図法 | 8.7 |
| **[ジョセフソン接合](./josephson-demo.html)** | ヒステリシス、サドルノード分岐 | 8.5 |
| **[ホップ分岐](./Strogatz-Hopfbifurcation-demo.html)** | 分岐点での安定性変化 | 8.2 |
| **[ホモクリニック分岐](./Strogatz-Homoclinicbifurcation-demo.html)** | サドル点へのループ接続 | 8.4 |
| **[無限周期分岐 (SNIPER)](./Strogatz-infiniteperiod-demo.html)** | ボトルネック効果 | 8.4 |

#### 9章：ローレンツ方程式とカオス

| デモ | 内容 | Strogatz節 |
|-----|------|-----------|
| **[カオス的な水車](./ch9-1-waterwheel.html)** | Malkus-Howard 水車を N=48 チェンバーで離散化、流入Q・漏れK・減衰νで定常/振動/カオス回転 | 9.1 |
| **[ローレンツ・アトラクター](./ch9-3-lorenz-attractor.html)** | x-z 位相図と y(t) 時系列、双子軌道モードで鋭敏な依存性を可視化、固定点 C± とホップ分岐 r_H をマーキング | 9.2-9.3 |
| **[ローレンツ写像](./ch9-4-lorenz-map.html)** | z の極大列から z_{n+1} vs z_n、\|f'\|>1 の直接確認 (カオスの直接証拠) | 9.4 |
| **[パラメーター空間の探索](./ch9-5-parameter-explorer.html)** | r=0.8〜214 のプリセットで各レジームをカタログ。間欠カオス、ノイズ的周期性、周期窓 | 9.5 |
| **[カオスマスク通信](./ch9-6-chaos-masking.html)** | Cuomo-Oppenheim の同期スキーム、x(t)+m(t) でマスク送信、受信側 (x_r, y_r, z_r) が同期して m を復元 | 9.6 |

#### 10章：1次元写像とカオス

| デモ | 内容 | Strogatz節 |
|-----|------|-----------|
| **[クモの巣図法 (8写像対応)](./ch10-1-cobweb.html)** | ロジスティック/cos/正弦/テント/10進シフト/2進シフト/線形/2次を切替、二分法で不動点検出 | 10.1 |
| **[ロジスティック時系列](./ch10-2-logistic-timeseries.html)** | r を変えて周期 1→2→4→8→カオスを時系列とヒストグラムで、周期自動検出 | 10.2 |
| **[軌道図 (分岐図)](./ch10-2-orbit-diagram.html)** | フラクタル構造、矩形ドラッグで拡大、ロジスティック/サイン/テント/三次に対応 | 10.2 |
| **[3周期窓と接線分岐](./ch10-4-period3-window.html)** | r₁ = 1+√8 ≈ 3.8284 で 3周期窓誕生、I型間欠性 (Pomeau-Manneville) | 10.4 |
| **[リアプノフ指数 λ(r)](./ch10-5-lyapunov.html)** | 周期 (λ<0) / 倍分岐 (λ=0) / カオス (λ>0) の対応、軌道図オーバーレイ可 | 10.5 |
| **[普遍性 (サイン vs ロジスティック)](./ch10-6-universality.html)** | U系列の定性的一致を分岐図で比較、超安定軌道 R_n から Feigenbaum δ を計算 | 10.6 |
| **[Feigenbaum くりこみ](./ch10-7-renormalization.html)** | f(x, R_n) と α·f²(x/α, R_{n+1}) の3パネル比較で自己相似性、α の経験的推定 | 10.7 |
| **[ロジスティック写像 (旧版)](./logistic-map-demo.html)** | クモの巣図法、周期倍分岐、Feigenbaum定数 | 10.3, 10.6 |
| **[円形写像のカオス](./Strogatz-hatten-circadianchaos-demo.html)** | Circle Map、概日リズム、アーノルドの舌 | 10.5 |

#### その他のデモ

| デモ | 内容 |
|-----|------|
| **[Van der Pol振動子](./Strogatz-Vanderpol-demo.html)** | リミットサイクルと非線形振動 |

---

### 🐰 Lotka-Volterraで学ぶ2次元力学系

**生態学モデルで非線形力学の概念を統合的に学ぶ**

Lotka-Volterraモデルのバリエーションを通じて、Strogatz 2-10章の主要概念を体験できます。

| デモ | モデル | 学べる概念 |
|-----|-------|----------|
| **[競争方程式](./lv-competition-demo.html)** | 2種競争 | 固定点分類、多様体、双安定性 (5-6章) |
| **[古典LV（被食-捕食）](./lv-classic-demo.html)** | 古典的LV | 中心点、保存系、構造不安定性 (6-7章) |
| **[Rosenzweig-MacArthur](./rosenzweig-macarthur-demo.html)** | 改良型LV | ホップ分岐、Paradox of Enrichment (8章) |
| **[離散LV](./lv-discrete-demo.html)** | 離散写像 | 周期倍分岐、カオスへの道 (10章) |

#### 概念マップ

```
Strogatz章     モデル/デモ
─────────────────────────────────────
5章 固定点分類    → 競争方程式
6章 多様体・中心点 → 競争 / 古典LV
7章 Bendixson    → 古典LV
8章 ホップ・ホモクリニック → Rosenzweig-MacArthur
10章 1次元写像    → ロジスティック写像
10章 周期倍分岐   → 離散LV / ロジスティック
9-10章 カオス    → 離散LV / ロジスティック / 3種系
```

---

### 🏀 NBA・バスケットボール研究

#### NBA 勢力図（ライブデータ連携）

| プロジェクト | 内容 |
|-----------|------|
| **[NBA ランドスケープ](./NBAlandscape.html)** | 2025-26シーズン全30チームの勢力図。ESPN APIによるライブスコア・順位表・ニュースフィード。Gemini APIによるAI更新機能。選手プロフィールリンク付き |
| **[プレーオフ](./playoffs.html)** | NBAプレーオフブラケット（SVG）。シリーズ詳報、ラウンド別フィルタ。オフシーズン中は順位表ベースの予想ブラケット表示 |
| **[オフシーズン](./offseason.html)** | NBAドラフト指名一覧（ESPN Draft API）、FA情報、ラスベガスサマーリーグスコアボード |
| **[WNBA & G League](./gleague-wnba.html)** | WNBAライブスコア・順位表・13チーム一覧＋地図。Gリーグ全30アフィリエイト提携表 |

#### バスケットボール学術研究

| プロジェクト | 内容 |
|-----------|------|
| **[バスケットボール研究マップ](./basketball-research-map.html)** | 10サブコミュニティの体系的マッピング。D3.jsによる近接ネットワーク可視化 |
| **[Oliver『Basketball on Paper』読解マップ](./oliver-research-tree.html)** | Dean Oliver (2004) の24章を5クラスタに整理し、27の後続研究との対応を可視化。D3.jsフォースグラフ |
| **[Oliver研究系譜フロー](./oliver-research-flow.html)** | Oliver由来の概念がどう学術・実務へ展開されたかを時系列で追う |
| **[バスケ学術研究タイムライン](./basketball-research-timeline.html)** | バイオメカニクス・医学・心理学・フィジオロジー・アナリティクス・AI/CV・コーチング等10分野の研究史 1985–2025 |

#### 参考資料（research/）
- `oliver-deep-research.md` — Oliver読解マップの元データ（章別命題・後続研究の詳細）
- `nba-reception-report.md` — LeBron James / Stephen Curry の米国内受容比較レポート
- `nba-reception-rationale.md` — NBA受容類型の根拠
- `nba-reception-types.png` — 受容類型の1ページ図

---

### 🌍 その他のプロジェクト

| プロジェクト | 内容 |
|-----------|------|
| **[古代ランドスケープ](./ancient-landscapes-by-claude.html)** | 古代史と地形的変化の可視化 |
| **[プロンプトエンジニアリング・ガイド](./prompt-engineering-guide.md)** | プロンプト設計の原則と実例 |

---

## 使い方

### インタラクティブデモの操作

各デモはブラウザで直接実行できます。基本的な操作は共通です：

- **スライダー**: パラメータをリアルタイムで調整して、システムの振る舞い変化を観察
- **相図上のクリック**: マウスで軌道の初期条件を指定、複数の軌道を同時にプロット
- **リセット/クリア**: アニメーション再スタート、軌道クリアなどのコントロール
- **マウスホバー**: エラーバーやツールチップで詳細情報を表示（一部デモ）

### データの検索

NBA ランドスケープなどは検索フィルタ機能を備えています。

---

## 技術情報

### フロントエンド（ブラウザデモ）

- HTML5 + Canvas + JavaScript
- モバイル対応（タッチ操作可能）
- 外部ライブラリ不要

### その他

- **生成ツール**: Python スクリプト

### 開発環境

- Git リポジトリ管理

---

## ライセンス・参考資料

- **Nonlinear Dynamics and Chaos**: Steven H. Strogatz（教科書）
- **ESJ Journals**: 日本生態学会（論文出典）
- **数値シミュレーション**: NumPy, SciPy, CUDA

---

## リンク

- **GitHub リポジトリ**: [eUmeda/Claude](https://github.com/eUmeda/Claude)
- **GitHub Pages**: <https://eumeda.github.io/Claude/>

---

*最終更新: 2026年5月14日*
