# ai-usage-tools — AI使用量ツール集

Claude と Codex のトークン使用量を表示する自作ツール群（旧名 claude-usage-tools）。2026-07-05 に各所（`~/scripts`、旧 `~/projects/claude_clock_widget`、`homeproject/usage_display`）から集約。

## 構成
- `claude_usage.py` — 使用量取得の共通ライブラリ（下記ツールが同ディレクトリから import する。**分離しないこと**）。macOS では認証情報を Keychain（`Claude Code-credentials`）から読む
- `codex_usage.py` — Codex 使用量の共通ライブラリ。API ではなく `~/.codex/sessions/` のログから最新の rate_limits を読むので、**値は最後に Codex を使った時点のもの**
- `macos_menubar/ai_usage.1m.py` — Mac のメニューバーに Claude / Codex の残量を二重リング（外側 5h 枠・内側 週枠）で表示する SwiftBar プラグイン（`1m` は更新間隔）。親ディレクトリの共通ライブラリを import するので、リポジトリ内に置いたまま SwiftBar のプラグインフォルダへシンボリックリンクする。Python 3.9+（Homebrew の python3 を優先して使う）。前回値キャッシュと通知済みフラグを SwiftBar のプラグインデータフォルダ（`$SWIFTBAR_PLUGIN_DATA_PATH`、なければ `~/.cache/ai-usage-tools`）の `menubar_state.json` に保存する
  - `macos_menubar/install.sh` — Mac 側セットアップ（python3・SwiftBar のインストール、プラグインのリンク、動作確認）を一括で行う
- `claude_widget.py` — デスクトップウィジェット。Claude Code のセッション開始フックで自動起動（`~/.claude/settings.json` にパス設定あり。**このファイルを動かしたらフックも更新**）
- `claude_dashboard.py` — ブラウザで見る使用量ダッシュボード（HTTPサーバー）
- `claude_monitor.py` — CLIモニター
- `clock_widget.py` — 使用量表示付き時計ウィジェット（旧 claude_clock_widget プロジェクト）
- `usage_display/` — Pico WH + 2.8インチTFT（ILI9341/MSP2807）で常時表示するデスクガジェット（旧 `homeproject/usage_display`。2026-06-22 コード作成済み・**部品待ち**）
  - `pc/send_usage.py` — PC側送信スクリプト
  - `pico/main.py` — Pico側表示プログラム

## 経緯
- **2026-07-05**: ホームディレクトリ整理の続きとして、散らばっていた使用量系プログラムをこのプロジェクトに集約。`claude_usage.py` の重複コピー（claude_clock_widget内、内容同一）は削除。
- **2026-10-20**: Codex の使用量も扱う方針にしたため、リポジトリ名を `claude-usage-tools` → `ai-usage-tools` に変更。
- **2026-10-20**: Mac メニューバー用の SwiftBar プラグインと Codex 用ライブラリを追加。
