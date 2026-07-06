# RengaBroker

**Claude Code 用端末環境ブローカー** — tmux / WezTerm のセッション・ペイン・プロセス状態を追跡し、AI エージェントが「自分が今どこにいるか」を把握して端末を自律操作できるようにする中間レイヤー。

> なんでみんな Claude Code 自身が、自分がどこで何をしているか?を知るためのブローカーを書かないんだ? — その答えとして書かれたのがこれです。

## なにができるか

- **状態監視**: tmux / WezTerm の全セッション・ウィンドウ・ペイン(実行コマンド、PID、cwd、tty、サイズ、アクティブ状態)を正規化された 1 つの JSON で取得
- **自己位置特定** (`whereami`): 呼び出したプロセスがどのペインにいるかを、環境変数 → tty → プロセス祖先の順で特定
- **操作**: 任意のペインへテキスト/キー送信 (`send`)、画面+スクロールバックのキャプチャ (`capture`)
- **常駐デーモン** (`serve`): 同じ機能を HTTP JSON API で提供。Claude Code からは `curl` 一発

依存ゼロ(Python 3.8+ 標準ライブラリのみ)、単一ファイル。Linux / macOS(tmux + WezTerm)、Windows(WezTerm)で動作。

## インストール

```bash
# このファイルをコピーするだけ
curl -fsSL https://raw.githubusercontent.com/eUmeda/Claude-public/main/rengabroker/rengabroker.py -o ~/bin/rengabroker
chmod +x ~/bin/rengabroker
```

または リポジトリを clone して `python3 rengabroker/rengabroker.py ...`。

## CLI の使い方

```bash
rengabroker backends          # どのバックエンドが生きているか
rengabroker snapshot          # 全状態を JSON で
rengabroker panes             # 全ペインのフラットな一覧
rengabroker whereami          # 「今どこ?」(呼び出し元シェルのペインを特定)

# ペイン %3 に「ls -la」をタイプして Enter
rengabroker send --target tmux:%3 --text "ls -la" --enter

# Ctrl-C を送る(tmux のキー名記法)
rengabroker send --target tmux:%3 --keys C-c

# WezTerm のペイン 7 の画面をスクロールバック 100 行込みで取得
rengabroker capture --target wezterm:7 --lines 100 --raw
```

ペインの指定は正規形式 `tmux:%5` / `wezterm:7`(`snapshot` / `panes` が返す `target` フィールドの値)。tmux ネイティブの `セッション名:ウィンドウ.ペイン` もそのまま通ります。

## 常駐デーモン(HTTP JSON API)

```bash
# 起動(デフォルト 127.0.0.1:8787。トークンは任意だが推奨)
rengabroker serve --port 8787 --token "$(openssl rand -hex 16)"
```

tmux 内に常駐させるなら:

```bash
tmux new-session -d -s broker 'RENGABROKER_TOKEN=secret rengabroker serve'
```

| エンドポイント | 内容 |
|---|---|
| `GET /health` | 生存確認とバージョン |
| `GET /backends` | バックエンドの可用性 |
| `GET /snapshot`(`?fresh=1` でキャッシュ無視) | 全状態 |
| `GET /panes` | 全ペインのフラット一覧 |
| `GET /whereami?pid=<pid>` | 指定 PID の所在ペイン |
| `POST /send` `{target, text?, keys?, enter?}` | キー送信 |
| `POST /capture` `{target, lines?}` | 画面キャプチャ |

トークンを設定した場合は `Authorization: Bearer <token>` ヘッダが必要です。

## Claude Code との連携例

Claude Code に CLAUDE.md 等でこう教えておくだけで、自分で状況把握して動きます:

```markdown
端末の状態把握と操作には RengaBroker を使うこと:
- 自分の位置: `rengabroker whereami`
- 全ペイン確認: `rengabroker panes`
- 別ペインでビルドを走らせ結果を読む:
  `rengabroker send --target tmux:%2 --text "make test" --enter`
  → 待ってから `rengabroker capture --target tmux:%2 --lines 50 --raw`
```

常駐デーモン経由なら:

```bash
curl -s -H "Authorization: Bearer $RENGABROKER_TOKEN" \
  http://127.0.0.1:8787/whereami?pid=$$
```

## アーキテクチャ

```
CLI (argparse)  ┐
                ├── Broker ── TmuxBackend    (tmux list-panes -F / send-keys / capture-pane)
HTTP (serve)    ┘     │  └─── WeztermBackend (wezterm cli list --format json / send-text / get-text)
                      └ スナップショットキャッシュ (TTL 1s) / target 解決 / whereami
```

- **正規化スキーマ**: どのバックエンドも `sessions → windows → panes` に揃え、ペインは `{backend, target, session, window_index, window_name, pane_id, title, command, pid, cwd, tty, active, width, height}`。
- **エラー耐性**: バイナリがない・サーバが起動していない・タイムアウト、はすべて `{"available": false, "reason": "..."}` に degrade。1 つのバックエンドの故障が全体を沈めない。
- **拡張**: `Backend` を継承して `make_backends()` に足すだけで新しい端末ツール(herdr 等)に対応可能。手順は [CLAUDE.md](./CLAUDE.md) 参照。

## テスト

```bash
python3 -m unittest discover -s rengabroker/tests -v
```

- ユニットテスト(19 件中 16 件): 缶詰の tmux / wezterm 出力を注入。マルチプレクサ不要でどこでも走る
- ライブスモークテスト(3 件): tmux がある環境でのみ自動実行。使い捨てセッションを作って send→capture ラウンドトリップまで実機検証

## セキュリティ上の注意

`send` は任意のペインに任意のキー入力を注入できます(それが目的の機能です)。

- デーモンは **127.0.0.1 バインドがデフォルト**。`--host 0.0.0.0` にする場合は必ず `--token` を設定すること
- トークンは `RENGABROKER_TOKEN` 環境変数でも渡せます
- マルチユーザ機では tmux ソケットの権限がそのままアクセス制御になります

## ライセンス

リポジトリ本体に準じます。
