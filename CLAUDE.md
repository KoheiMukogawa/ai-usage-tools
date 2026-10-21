# ai-usage-tools — AI使用量ツール集

Claude と Codex のトークン使用量を表示する自作ツール群（旧名 claude-usage-tools）。2026-07-05 に各所（`~/scripts`、旧 `~/projects/claude_clock_widget`、`homeproject/usage_display`）から集約。

配布用の説明は `README.md`（Mac / Windows（WSL なし）/ Windows（WSL）の 3 通りの導線）。**導入手順や対応環境を変えたら README も更新すること。**

## 構成
- `claude_usage.py` — 使用量取得の共通ライブラリ（下記ツールが同ディレクトリから import する。**分離しないこと**）。macOS では認証情報を Keychain（`Claude Code-credentials`）から読む
- `codex_usage.py` — Codex 使用量の共通ライブラリ。インストール済みの Codex CLI を `codex app-server`（JSON-RPC over stdio、1行1JSON）で起動し、`initialize` → `initialized` → `account/rateLimits/read`（5h=primary / 週=secondary、usedPercent・resetsAt）と `account/read`（email・planType）を取る。トークン更新は Codex 側がやる。CLI が無い・失敗時は `~/.codex/sessions/` のログの最新 rate_limits（**最後に Codex を使った時点の値**）にフォールバック。app-server は experimental なので、形式が変わったら `python3 codex_usage.py --raw` で確認。スキーマは `codex app-server generate-json-schema --out DIR` で生成できる。SwiftBar/トレイは PATH が最小なので `EXTRA_BIN_DIRS`（~/.local/bin、Homebrew、npm、nvm）も探し、npm 版の `#!/usr/bin/env node` 対策で codex と同じディレクトリを PATH に足して起動する
- `usage_snapshot.py` — メニューバー／トレイ共通の中核（サービスの取得、前回値キャッシュ、通知判定、二重リングアイコンの PNG 描画）。Mac 版・Windows 版の両方が使う。**表示サービスは自動判定**（ログイン痕跡があるものだけ。何も無ければ Claude を点線で1つ）、`~/.config/ai-usage-tools/config.json`（Windows は `%APPDATA%`）の `{"services": [...]}` で固定可。サービス追加は `SERVICES` と `_detected`/`_fetch`/`_account` に足す。取得間隔は `FETCH_INTERVAL`（Codex は 290 秒。間の回はキャッシュをそのまま使い、stale 扱いにしない）。Claude の HTTP 429 は `UsageError.retry_after`（Retry-After、なければ 300 秒）で state の `backoff` に入り、その間は取得せず前回値を stale 表示
- `macos_menubar/ai_usage.1m.py` — Mac のメニューバーに Claude / Codex の残量を二重リング（外側 5h 枠・内側 週枠）で表示する SwiftBar プラグイン（`1m` は更新間隔）。親ディレクトリの共通ライブラリを import するので、リポジトリ内に置いたまま SwiftBar のプラグインフォルダへシンボリックリンクする。Python 3.8+（Homebrew の python3 を優先して使う。全 Python コードは 3.8 互換・標準ライブラリのみ・Windows でも動くように保つ）。前回値キャッシュと通知済みフラグを SwiftBar のプラグインデータフォルダ（`$SWIFTBAR_PLUGIN_DATA_PATH`、なければ `~/.cache/ai-usage-tools`）の `menubar_state.json` に保存する
  - `macos_menubar/install.sh` — Mac 側セットアップ（python3・SwiftBar のインストール、プラグインのリンク、動作確認）を一括で行う。`--uninstall` でプラグインを外す
- `windows_tray/` — Windows のタスクトレイに Claude / Codex を別々の二重リングアイコンで表示。Claude Code / Codex を Windows で直接使う人（Native）と WSL で使う人（Wsl）の両対応
  - `usage_json.py` — スナップショットをアイコン PNG・ツールチップ・メニュー文言込みの JSON で出力。Windows Python でも WSL の python3 でも動く。状態は `%LOCALAPPDATA%\ai-usage-tools\tray_state.json`（WSL では `~/.cache/ai-usage-tools/`）
  - `ai_usage_tray.ps1` — Windows 側（PowerShell 5.1 + WinForms NotifyIcon）。1分ごとに usage_json.py を呼んで描くだけ（`-Mode Native` は Windows の python.exe、`-Mode Wsl` は `wsl.exe` 経由）。**ASCII のみで書くこと**（5.1 は BOM なし UTF-8 を誤読する。日本語文言は JSON 側に置く）
  - `install.ps1` / `install.cmd` — Native 用セットアップ（install.cmd はダブルクリック用ラッパー）。Python 3.8+ を探し、**clone 内の ps1 をコピーせず直接**起動する非表示ランチャー `AI Usage Tray.vbs` をスタートアップに置く（git pull で更新が届く）。**install.ps1 は日本語を含むので UTF-8 BOM 付きで保存**。`-Uninstall` で解除
  - `install.sh` — Wsl 用セットアップ（WSL から実行）。中身は install.ps1 と同等。`--install-codex` で WSL に Codex CLI を公式インストーラー（releases の install.sh）で入れる。**単体バイナリ（codex-x86_64-unknown-linux-musl）だけ入れると app-server は動くが対話画面が "no complete local package" で起動しないので使わないこと**。`--uninstall` で解除
  - トレイは取得のたびに `%LOCALAPPDATA%\ai-usage-tools\tray_status.json`（pid・last_success・last_error）を書く。**トレイが動いているかはこれで判定すること**（`tray_state.json` はインストールの事前チェックでも更新されるので証拠にならない）。両セットアップは起動後にこれを最大45秒待って成否を表示する
  - **WSL 版（install.sh）は ps1 を `%LOCALAPPDATA%\ai-usage-tools` にコピーするので、ps1 を変更したら再実行が必要**（ログオン直後に \\wsl.localhost の ps1 を読むと WSL 起動前で失敗しうるため）。Python 側の変更はどちらも即反映。.vbs ランチャーは日本語パス対策で UTF-16 で書く
- `claude_widget.py` — デスクトップウィジェット。Claude Code のセッション開始フックで自動起動（`~/.claude/settings.json` にパス設定あり。**このファイルを動かしたらフックも更新**）
- `claude_dashboard.py` — ブラウザで見る使用量ダッシュボード（HTTPサーバー）
- `claude_monitor.py` — CLIモニター
- `clock_widget.py` — 使用量表示付き時計ウィジェット（旧 claude_clock_widget プロジェクト）
- `usage_display/` — Pico WH + 2.8インチTFT（ILI9341/MSP2807）で常時表示するデスクガジェット（旧 `homeproject/usage_display`。2026-06-22 コード作成済み・**部品待ち**）
  - `pc/send_usage.py` — PC側送信スクリプト
  - `pico/main.py` — Pico側表示プログラム

## テスト
- `python3 -m unittest discover -s tests -v`（標準ライブラリのみ）。偽の `codex` で app-server のやり取りも Linux/Mac/Windows で検証する
- `.github/workflows/ci.yml` が push ごとに Linux(3.8/3.12)・macOS・Windows でテスト、bash -n / shellcheck、PowerShell 5.1 での構文チェックと「トレイ ps1 は ASCII のみ・install.ps1 は BOM 付き」を検査
- 動作確認でパイプに `head` をつなぐと SIGPIPE でセットアップが途中で止まるので注意

## 経緯
- **2026-07-05**: ホームディレクトリ整理の続きとして、散らばっていた使用量系プログラムをこのプロジェクトに集約。`claude_usage.py` の重複コピー（claude_clock_widget内、内容同一）は削除。
- **2026-10-20**: Codex の使用量も扱う方針にしたため、リポジトリ名を `claude-usage-tools` → `ai-usage-tools` に変更。
- **2026-10-20**: Mac メニューバー用の SwiftBar プラグインと Codex 用ライブラリを追加。
- **2026-10-20**: Windows タスクトレイ版を追加。共通処理を `usage_snapshot.py` に切り出し。
- **2026-10-21**: 配布できる形に整備。Windows（WSL なし）対応、README 追加、アカウント表示を追加。
- **2026-10-21**: Codex の取得を `codex app-server` 方式に変更（直接 HTTP で叩く方式は廃止）。
