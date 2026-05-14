# Prompt Engineering 総合ガイド

> Anthropic公式ドキュメントに基づくプロンプトエンジニアリング手法の統合リファレンス。
> NBAチームレポート自動生成プロンプトの設計根拠としても参照する。

---

## 目次

1. [概要（Overview）](#1-概要overview)
2. [プロンプトジェネレーター](#2-プロンプトジェネレーター)
3. [明確・直接的に書く（Be Clear and Direct）](#3-明確直接的に書くbe-clear-and-direct)
4. [例を使う（Multishot Prompting）](#4-例を使うmultishot-prompting)
5. [Claudeに考えさせる（Chain of Thought）](#5-claudeに考えさせるchain-of-thought)
6. [XMLタグで構造化する](#6-xmlタグで構造化する)
7. [ロールを与える（System Prompts）](#7-ロールを与えるsystem-prompts)
8. [プロンプトを連鎖させる（Prompt Chaining）](#8-プロンプトを連鎖させるprompt-chaining)
9. [長文コンテキストのコツ](#9-長文コンテキストのコツ)

---

## 1. 概要（Overview）

### 前提条件

プロンプトエンジニアリングを始める前に、以下を整理しておくこと：

1. ユースケースの成功基準を明確に定義する
2. その基準に対して経験的にテストする方法を用意する
3. 改善したい最初のドラフトプロンプトを持つ

### プロンプトエンジニアリング vs ファインチューニング

プロンプトエンジニアリングはファインチューニングより遥かに速く、以下の利点がある：

- **リソース効率**: ファインチューニングにはハイエンドGPUと大容量メモリが必要。プロンプトエンジニアリングはテキスト入力のみ
- **コスト効率**: クラウドAIサービスでは、ファインチューニングに大きなコストがかかる
- **モデル更新への対応**: プロバイダがモデルを更新しても、プロンプトは通常そのまま動く
- **時間節約**: ファインチューニングは数時間〜数日。プロンプトエンジニアリングは即座に結果が得られる
- **データ不要**: ファインチューニングには大量のタスク固有ラベル付きデータが必要。プロンプトエンジニアリングはfew-shotやzero-shotで動く
- **柔軟性**: 様々なアプローチを素早く試し、即座に結果を確認できる
- **ドメイン適応**: プロンプトにドメイン固有のコンテキストを提供するだけで新領域に適応可能
- **理解力向上**: 検索ドキュメントなどの外部コンテンツの理解・活用にはファインチューニングより効果的
- **汎用知識の保持**: ファインチューニングは壊滅的忘却のリスクがある。プロンプトエンジニアリングはモデルの広範な能力を維持
- **透明性**: プロンプトは人間が読める形式で、モデルが何の情報を受け取っているかが明確

### 推奨順序

効果が広い順に並べてある。トラブルシューティング時もこの順序で試すとよい：

1. プロンプトジェネレーター
2. 明確・直接的に書く
3. 例を使う（multishot）
4. Claudeに考えさせる（chain of thought）
5. XMLタグを使う
6. ロールを与える（system prompts）
7. プロンプトを連鎖させる
8. 長文コンテキストのコツ

---

## 2. プロンプトジェネレーター

「白紙ページ問題」を解決するためのツール。Claudeにタスクに最適化されたプロンプトテンプレートを生成させる。

- [Anthropic Console](https://console.anthropic.com/dashboard) で直接利用可能
- [Google Colab notebook](https://anthropic.com/metaprompt-notebook/) で仕組みを分析可能（APIキーが必要）

ジャンプオフポイントとして使い、そこからテストとイテレーションを重ねる。

---

## 3. 明確・直接的に書く（Be Clear and Direct）

Claudeを「記憶喪失の優秀な新入社員」と考える。あなたの規範、スタイル、ガイドライン、作業方法のコンテキストがない状態。説明が正確であるほど、レスポンスの質が上がる。

**黄金律**: プロンプトを、タスクのコンテキストが最小限の同僚に見せて、指示に従ってもらう。同僚が混乱するなら、Claudeも混乱する。

### 方法

- **コンテキスト情報を与える**:
  - タスク結果の使用目的
  - 出力の対象読者
  - タスクが含まれるワークフローと、その中での位置
  - 最終目標、または成功した完了とはどのような状態か
- **具体的に指示する**: 例えば「コードだけを出力し、他は何も出力しない」と明示する
- **手順を連番で示す**: 番号付きリストや箇条書きで、正確にタスクを実行させる

### 例：顧客フィードバックの匿名化

**不明確なプロンプト**:
```
Please remove all personally identifiable information from these customer feedback messages: {{FEEDBACK_DATA}}
```

**明確なプロンプト**:
```
Your task is to anonymize customer feedback for our quarterly review.

Instructions:
1. Replace all customer names with "CUSTOMER_[ID]" (e.g., "Jane Doe" → "CUSTOMER_001").
2. Replace email addresses with "EMAIL_[ID]@example.com".
3. Redact phone numbers as "PHONE_[ID]".
4. If a message mentions a specific product (e.g., "AcmeCloud"), leave it intact.
5. If no PII is found, copy the message verbatim.
6. Output only the processed messages, separated by "---".

Data to process: {{FEEDBACK_DATA}}
```

不明確なプロンプトでは顧客名が残るなどのミスが発生する。明確なプロンプトでは一貫したフォーマットで正確に匿名化される。

### 例：インシデントレスポンス

**曖昧なプロンプト**:
```
Analyze this AcmeCloud outage report and summarize the key points.
{{REPORT}}
```

**詳細なプロンプト**:
```
Analyze this AcmeCloud outage report. Skip the preamble. Keep your response terse and write only the bare bones necessary information. List only:
1) Cause
2) Duration
3) Impacted services
4) Number of affected users
5) Estimated revenue loss.

Here's the report: {{REPORT}}
```

曖昧なプロンプトでは冗長なテキストと異なるフォーマットが返る。詳細なプロンプトでは簡潔で構造化された出力が得られる。

---

## 4. 例を使う（Multishot Prompting）

例はClaudeに正確な出力を生成させるための最強のショートカット。few-shot（multishot）プロンプティングは、構造化された出力や特定フォーマットへの準拠が必要なタスクに特に効果的。

**Power tip**: 3〜5個の多様で関連性のある例を含める。例が多いほどパフォーマンスが向上する（特に複雑なタスク）。

### 効果的な例の作り方

- **関連性**: 実際のユースケースを反映する
- **多様性**: エッジケースや課題をカバーし、意図しないパターンをClaudeが拾わないよう十分に変化させる
- **明確性**: `<example>` タグ（複数なら `<examples>` タグ内にネスト）で構造化する

### 例：顧客フィードバックの分析

**例なし**のプロンプト:
```
Analyze this customer feedback and categorize the issues. Use these categories: UI/UX, Performance, Feature Request, Integration, Pricing, and Other. Also rate the sentiment (Positive/Neutral/Negative) and priority (High/Medium/Low).

Here is the feedback: {{FEEDBACK}}
```

**例付き**のプロンプト:
```
Our CS team is overwhelmed with unstructured feedback. Your task is to analyze feedback and categorize issues for our product and engineering teams. Use these categories: UI/UX, Performance, Feature Request, Integration, Pricing, and Other. Also rate the sentiment (Positive/Neutral/Negative) and priority (High/Medium/Low). Here is an example:

<example>
Input: The new dashboard is a mess! It takes forever to load, and I can't find the export button. Fix this ASAP!
Category: UI/UX, Performance
Sentiment: Negative
Priority: High
</example>

Now, analyze this feedback: {{FEEDBACK}}
```

例なしでは各カテゴリに長い説明が付き、複数カテゴリの列挙が漏れる。例付きでは一貫したフォーマットで正確にカテゴライズされる。

---

## 5. Claudeに考えさせる（Chain of Thought）

研究、分析、問題解決など複雑なタスクでは、Claudeに考える余地を与えるとパフォーマンスが劇的に向上する。

### メリット

- **正確性**: 問題をステップごとに分解することでエラーを減らす（数学、ロジック、分析、複雑なタスク全般）
- **一貫性**: 構造化された思考がまとまりのある応答につながる
- **デバッグ**: Claudeの思考過程を見ることで、プロンプトのどこが不明確かを特定できる

### デメリット

- 出力長が増えるためレイテンシに影響する可能性
- すべてのタスクに深い思考が必要なわけではない。パフォーマンスとレイテンシのバランスを考慮して使う

### 3段階のCoT手法（シンプル→複雑の順）

#### 1. 基本プロンプト

```
Think step-by-step
```
を含めるだけ。*どう*考えるかのガイダンスがないため、タスク固有の場面では不十分なことがある。

#### 2. ガイド付きプロンプト

思考プロセスの具体的なステップを示す：

```
Think before you write the email. First, think through what messaging might appeal to this donor given their donation history and which campaigns they've supported in the past. Then, think through what aspects of the Care for Kids program would appeal to them, given their history. Finally, write the personalized donor email using your analysis.
```

#### 3. 構造化プロンプト（XMLタグ付き）

`<thinking>` と `<answer>` タグで推論と最終回答を分離する：

```
Think before you write the email in <thinking> tags. First, think through what messaging might appeal to this donor given their donation history... Finally, write the personalized donor email in <email> tags, using your analysis.
```

### 例：投資アドバイス

**CoTなし**: 表面的で、潜在的な結果を定量化せず、歴史的な市場パフォーマンスを考慮しない推薦が返る。

**CoTあり**: `<thinking>` タグ内で両オプションの5年リターンを計算し、リスク許容度を分析し、歴史的な市場変動を考慮した上で、`<answer>` タグで根拠のある推薦を出す。

---

## 6. XMLタグで構造化する

プロンプトに複数のコンポーネント（コンテキスト、指示、例）が含まれる場合、XMLタグが威力を発揮する。Claudeがプロンプトをより正確に解析し、高品質な出力につながる。

### メリット

- **明確性**: プロンプトの異なる部分を明確に分離し、構造を確保
- **正確性**: Claudeがプロンプトの一部を誤解するエラーを削減
- **柔軟性**: 全体を書き直さずに部分の追加・削除・修正が容易
- **解析性**: Claudeの出力にもXMLタグを使わせることで、後処理での特定部分の抽出が容易に

### ベストプラクティス

1. **一貫性**: プロンプト全体で同じタグ名を使い、コンテンツに言及する際もそのタグ名を参照する（例: `Using the contract in <contract> tags...`）
2. **ネスト**: 階層的なコンテンツにはタグをネストする `<outer><inner></inner></outer>`
3. **組み合わせ**: XMLタグをmultishotプロンプティング（`<examples>`）やchain of thought（`<thinking>`, `<answer>`）と組み合わせると、超構造化・高パフォーマンスなプロンプトが作れる

**注意**: Claudeが特別に訓練された「正規」のXMLタグ名はない。囲む情報に意味が通るタグ名を推奨。

### 例：財務レポート生成

**XMLタグなし**:
```
You're a financial analyst at AcmeCorp. Generate a Q2 financial report for our investors. Include sections on Revenue Growth, Profit Margins, and Cash Flow, like with this example from last year: {{Q1_REPORT}}. Use data points from this spreadsheet: {{SPREADSHEET_DATA}}. The report should be extremely concise, to the point, professional, and in list format. It should and highlight both strengths and areas for improvement.
```

**XMLタグあり**:
```
You're a financial analyst at AcmeCorp. Generate a Q2 financial report for our investors.

AcmeCorp is a B2B SaaS company. Our investors value transparency and actionable insights.

Use this data for your report:
<data>{{SPREADSHEET_DATA}}</data>

<instructions>
1. Include sections: Revenue Growth, Profit Margins, Cash Flow.
2. Highlight strengths and areas for improvement.
</instructions>

Make your tone concise and professional. Follow this structure:
<formatting_example>{{Q1_REPORT}}</formatting_example>
```

XMLタグなしでは、Q1レポート例とスプレッドシートデータの境界をClaudeが誤解するリスクがある。XMLタグありでは各セクションが明確に分離される。

---

## 7. ロールを与える（System Prompts）

`system` パラメータでClaudeにロールを与えると、パフォーマンスが劇的に向上する。適切なロールは、汎用アシスタントをバーチャルな領域専門家に変える。

**Tips**:
- `system` パラメータはロール設定に使う。タスク固有の指示は `user` ターンに入れる
- ロールを実験する！同じデータでも `data scientist` と `marketing strategist` では異なるインサイトが得られる

### メリット

- **精度向上**: 法律分析や財務モデリングなど複雑なシナリオでパフォーマンスが大幅に向上
- **トーン調整**: CFOの簡潔さやコピーライターの華やかさなど、コミュニケーションスタイルを調整
- **フォーカス強化**: ロールコンテキストを設定することで、Claudeがタスク要件の範囲内に留まりやすくなる

### 例：法的契約分析

**ロールなし**: 「全体的に標準的な契約に見える」という表面的な分析。

**ロールあり**（Fortune 500テック企業のGeneral Counsel）: 500ドルの損害賠償上限の危険性、ベンダーの過失に対する免責条項のリスク、IP共同所有の問題を具体的に指摘し、各条項に「拒否」の推奨と代替案を提示。

### 例：財務分析

**ロールなし**: 基本的な数字の要約のみ。

**ロールあり**（高成長B2B SaaS企業のCFO、取締役会での報告）: SMBセグメントの5%減少を指摘し、マーケティング予算の20%再配分を提案。AI機能へのR&D投資がEBITDAを圧迫しているがエンタープライズの粘着性に不可欠と判断。CAC上昇への対策として非必須の採用凍結とセールスファネル分析を推奨。

---

## 8. プロンプトを連鎖させる（Prompt Chaining）

複雑なタスクを1つのプロンプトで処理しようとすると、Claudeがステップを見落とすことがある。プロンプトチェイニングは、タスクを小さく管理可能なサブタスクに分割する手法。

### メリット

1. **正確性**: 各サブタスクがClaudeの全注意力を得る
2. **明確性**: サブタスクがシンプルなほど、指示と出力が明確になる
3. **追跡可能性**: チェーン内の問題箇所を容易に特定・修正できる

### いつ使うか

研究の統合、文書分析、反復的なコンテンツ作成など、複数ステップのタスクに使う。複数の変換、引用、指示を含むタスクでは、チェイニングがステップの欠落や誤処理を防ぐ。

### 方法

1. **サブタスクを特定**: タスクを明確な連続ステップに分解
2. **XMLで受け渡し**: XMLタグを使ってプロンプト間で出力を渡す
3. **単一目標**: 各サブタスクに単一の明確な目標を持たせる
4. **反復改善**: Claudeのパフォーマンスに基づいてサブタスクを改善

### チェーンワークフローの例

- **コンテンツ作成パイプライン**: 調査 → アウトライン → ドラフト → 編集 → フォーマット
- **データ処理**: 抽出 → 変換 → 分析 → 可視化
- **意思決定**: 情報収集 → 選択肢列挙 → 各分析 → 推奨
- **検証ループ**: コンテンツ生成 → レビュー → 改善 → 再レビュー

### 自己修正チェーン

Claudeに自分の作業をレビューさせるチェーンが作れる。高リスクタスクでのエラー捕捉と出力改善に有効。

**3ステップの例**（医学論文の要約）:

1. **Prompt 1**: 論文を要約（方法論、発見、臨床的意義に焦点）
2. **Prompt 2**: 要約を原論文と照合し、正確性・明確性・完全性をA-Fで評価
3. **Prompt 3**: フィードバックに基づいて要約を改善

### 法的契約分析の比較

**チェイニングなし**: 1プロンプトでリスク分析とメール起草を指示 → Claudeがメールに「提案された変更」を含め忘れる。

**チェイニングあり**:
1. Prompt 1: リスク分析のみ → `<risks>` タグで出力
2. Prompt 2: リスク分析結果を入力としてメール起草 → 具体的な変更提案を含む構造化されたメール
3. Prompt 3: メールのトーン・明確性・専門性を評価

**最適化Tip**: 独立したサブタスク（複数文書の分析など）は別プロンプトにして並列実行すると速度が上がる。

---

## 9. 長文コンテキストのコツ

Claudeの拡張コンテキストウィンドウ（Claude 3モデルで200Kトークン）を活用するためのガイド。

### 必須Tips

#### 長文データは先頭に配置する

長いドキュメントや入力（約20K+トークン）はプロンプトの先頭、クエリ・指示・例の上に配置する。テストではクエリを末尾に置くことで、特に複雑な複数文書入力で応答品質が最大30%向上。

#### ドキュメントの構造化にXMLタグを使う

複数ドキュメントを扱う場合、各ドキュメントを `<document>` タグで囲み、`<document_content>` と `<source>`（他のメタデータ）サブタグで明確化する：

```xml
<documents>
  <document index="1">
    <source>annual_report_2023.pdf</source>
    <document_content>
      {{ANNUAL_REPORT}}
    </document_content>
  </document>
  <document index="2">
    <source>competitor_analysis_q2.xlsx</source>
    <document_content>
      {{COMPETITOR_ANALYSIS}}
    </document_content>
  </document>
</documents>

Analyze the annual report and competitor analysis. Identify strategic advantages and recommend Q3 focus areas.
```

#### 引用で応答を根拠付ける

長文ドキュメントタスクでは、タスク実行前にまず関連部分を引用するようClaudeに指示する。ドキュメントの残りの「ノイズ」を除去するのに役立つ：

```xml
You are an AI physician's assistant. Your task is to help doctors diagnose possible patient illnesses.

<documents>
  <document index="1">
    <source>patient_symptoms.txt</source>
    <document_content>
      {{PATIENT_SYMPTOMS}}
    </document_content>
  </document>
  <document index="2">
    <source>patient_records.txt</source>
    <document_content>
      {{PATIENT_RECORDS}}
    </document_content>
  </document>
</documents>

Find quotes from the patient records and appointment history that are relevant to diagnosing the patient's reported symptoms. Place these in <quotes> tags. Then, based on these quotes, list all information that would help the doctor diagnose the patient's symptoms. Place your diagnostic information in <info> tags.
```

---

## 参考リンク

- [Anthropic Prompt Library](https://docs.anthropic.com/en/resources/prompt-library/library)
- [GitHub Prompting Tutorial](https://github.com/anthropics/prompt-eng-interactive-tutorial)
- [Google Sheets Prompting Tutorial](https://docs.google.com/spreadsheets/d/19jzLgRruG9kjUQNKtCg1ZjdD6l6weA6qRXG5zLIAhC8)
- [Anthropic Console (Prompt Generator)](https://console.anthropic.com/dashboard)
