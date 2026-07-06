# RengaBroker — Claude Code 用端末環境ブローカー

## 目標

Claude Code(などの端末内エージェント)が「自分が今どこにいるか」を自力で把握し、
tmux / WezTerm のペインを自律的に監視・操作できるようにする中間レイヤー。
人間がペイン間で手作業コピペする代わりに、AI がブローカーに問い合わせて動く。

- セッション・ウィンドウ・ペイン・プロセス状態を正規化された JSON で提供
- `whereami` で呼び出しプロセスの所在(どのペインか)を特定
- 任意のペインへのキー送信(`send`)と画面キャプチャ(`capture`)
- ワンショット CLI と常駐 HTTP デーモン(`serve`)の両方を同じコアで提供

## 制約(変更時も必ず守ること)

1. **Python 3.8+ 標準ライブラリのみ**。pip 依存を追加しない。1ファイルコピーで動くこと。
2. **クロスプラットフォーム**: Linux / macOS(tmux + WezTerm)、Windows(WezTerm のみ)。
   `ps` や `/proc` に依存するコードは必ずフォールバック付きで。
3. **エラー耐性**: バイナリ欠如・サーバ未起動・タイムアウトは
   `{"available": false, "reason": ...}` に degrade する。トレースバックで死なない。
   1つのバックエンドの故障が他のバックエンドやスナップショット全体を沈めない。
4. **セキュリティ**: HTTP デーモンはデフォルト 127.0.0.1 バインド。
   トークン(`--token` / `$RENGABROKER_TOKEN`)は Bearer 認証。
   外部バインドをデフォルトにしない。

## アーキテクチャ

```
rengabroker.py(単一ファイル)
├── default_runner()        subprocess 実行(テストでは FakeRunner に差し替え)
├── Backend                  アダプタ基底クラス
│   ├── TmuxBackend          tmux list-panes -a -F / send-keys / capture-pane
│   └── WeztermBackend       wezterm cli list --format json / send-text / get-text
├── Broker                   集約・キャッシュ(TTL)・target解決・whereami
├── BrokerHTTPHandler        HTTP JSON API(CLI と同じ Broker を共有)
└── main()                   argparse CLI
```

- ペイン target の正規形式は `tmux:%5` / `wezterm:7`。プレフィックスなしの
  `session:win.pane` は tmux ネイティブ target として tmux に委譲。
- `whereami` の探索順: ①環境変数(`TMUX_PANE` / `WEZTERM_PANE`)
  ②制御端末 tty の一致 ③プロセス祖先にペインの shell PID(tmux のみ)。

## 既知のハマりどころ

- **tmux の `-F` 出力は制御文字をエスケープする**(`\x1f` → 文字列 `\037`、
  タブ → `_`)。区切り文字は印字可能な `UNIT_SEP = "@@RB1F@@"` を使う。
  制御文字ベースの区切りに戻さないこと。
- `wezterm cli list` は pane の実行コマンド・PID を返さない(`command`/`pid` は null)。
- `tmux send-keys` は `-l --` で literal 送信。`--` がないと `-` で始まるテキストが
  オプション扱いされる。

## テスト

```bash
python3 -m unittest discover -s rengabroker/tests -v
```

- ユニットテスト: FakeRunner に缶詰出力を注入。tmux 不要でどこでも走る。
- ライブスモークテスト: tmux が使える環境でのみ自動実行(なければ skip)。
  使い捨てセッション `rengabroker-test-*` を作成し、snapshot / send /
  capture / whereami を実機で検証して kill する。

コード変更時は必ず両方をパスさせること。HTTP 層を触ったら手動スモークも:

```bash
python3 rengabroker/rengabroker.py serve --port 8791 --token t &
curl -s -H "Authorization: Bearer t" http://127.0.0.1:8791/snapshot
```

## バックエンド追加の手順(herdr など)

1. `Backend` を継承し `name` / `available()` / `snapshot()` / `send()` /
   `capture()` を実装(所在特定に対応するなら `locate(env, pid)` も)。
2. `snapshot()` はペイン schema(`Backend.snapshot` の docstring 参照)に正規化する。
   `target` は `"<name>:<id>"` 形式。
3. `make_backends()` にインスタンスを追加。
4. `tests/test_rengabroker.py` に FakeRunner ベースのテストを追加。
5. ツール固有の失敗はすべて `CommandError` か degrade に閉じ込める(制約3)。
