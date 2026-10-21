# ai-usage-tools

Claude（Claude Code）と Codex の **使用量の残り** を、Mac のメニューバー / Windows のタスクトレイに円グラフで常時表示するツールです。

```
 Mac メニューバー:   ◎ ◎  🔋 📶 10:30        Windows タスクトレイ:  ^  ◎ ◎  🔊 📶 10:30
                    │ └ Codex（緑）                                 │ └ Codex（緑）
                    └ Claude（オレンジ）                            └ Claude（オレンジ）
```

- **使っているサービスだけ表示**: その PC でログインしているサービス（Claude / Codex）を自動で見つけて、1 サービス 1 リングで表示。あとから Codex を使い始めれば、何もしなくてもリングが増えます
- **二重リング**: 外側が 5 時間枠、内側が週枠の **残量**（色付きの部分が残り。使うほど短くなる）
- 残り 20% 未満でリングが赤、0% でリング全体が赤
- クリックで詳細（残り % とリセット時刻、ログイン中のアカウントとプラン）
- 残りが 20% / 5% を切ると OS の通知でお知らせ
- 取得に失敗したときは直近（3 時間以内）の値を薄く表示、データが無いときは点線リング
- 1 分ごとに自動更新（Claude がアクセス過多（HTTP 429）を返したときは、指示された時間だけ待って再開）

### リングの見方

![リングの状態（左から：通常／残り少ない／取得失敗中の前回値／データなし／残り 0%）](docs/ring-states.png)

| 通常 | 残り 20% 未満 | 取得失敗中（直近の値を薄く表示） | データなし・未ログイン | 残り 0% |
|:-:|:-:|:-:|:-:|:-:|
| 色付きの部分が残り | その枠が赤 | 色が薄くなる | 点線 | リング全体が赤 |

> [!WARNING]
> Claude は **公式には公開されていないエンドポイント** から、Codex は Codex CLI の **実験的な（experimental）app-server 機能** から使用量を読んでいます。
> 各サービスのアップデートで予告なく動かなくなる可能性がある、個人用のツールとして使ってください。

## 対応環境

| 環境 | 表示場所 | 必要なもの |
|---|---|---|
| macOS | メニューバー | [Homebrew](https://brew.sh)（Python 3・[SwiftBar](https://swiftbar.app) はセットアップで自動インストール） |
| Windows（Claude Code / Codex を Windows で直接使う） | タスクトレイ | Python 3.8 以上、Windows PowerShell 5.1（標準搭載） |
| Windows（Claude Code / Codex を WSL で使う） | タスクトレイ | WSL の python3（Ubuntu なら標準搭載） |

どの環境でも、表示したいサービス（Claude Code / Codex CLI）が **その PC に入っていてログイン済み** であることが前提です。どちらか片方だけでも使えます（何も見つからないときは、ログインを促す点線リングを 1 つ表示します）。

## インストール

### macOS

```sh
git clone https://github.com/KoheiMukogawa/ai-usage-tools.git ~/ai-usage-tools
~/ai-usage-tools/macos_menubar/install.sh
```

途中で Keychain へのアクセス許可を求められたら「常に許可」を選んでください（Claude Code のログイン情報は Keychain にあります）。

### Windows（WSL なし）

1. Python が無ければ入れる（PowerShell で）:
   ```powershell
   winget install Python.Python.3.12
   ```
2. このリポジトリを取得する — `git clone https://github.com/KoheiMukogawa/ai-usage-tools.git`
   （git が無ければ GitHub の「Code → Download ZIP」で取得して展開しても OK。置いた場所から動かさないこと）
3. `windows_tray\install.cmd` をダブルクリック

### Windows（WSL）

WSL のターミナルで:

```sh
git clone https://github.com/KoheiMukogawa/ai-usage-tools.git ~/ai-usage-tools
~/ai-usage-tools/windows_tray/install.sh
```

WSL に Codex CLI が入っていなければ、OpenAI 公式のインストーラー（Node.js 不要）で入れられます:

```sh
~/ai-usage-tools/windows_tray/install.sh --install-codex
codex login --device-auth
```

### インストール後

- **Windows でアイコンが見当たらない**: トレイの「^」の中を確認。常に表示するには 設定 → 個人用設定 → タスク バー → 「その他のシステム トレイ アイコン」で Windows PowerShell をオン
- **通知**: Mac は「スクリプトエディタ」からの通知として届きます。初回に許可を求められたら許可してください

## 表示するサービスを固定する

通常は自動判定ですが、次のファイルを置くと表示するサービスを固定できます（ログインしていても非表示にしたいときなど）。

| 環境 | 場所 |
|---|---|
| macOS / WSL | `~/.config/ai-usage-tools/config.json` |
| Windows（WSL なし） | `%APPDATA%\ai-usage-tools\config.json` |

```json
{"services": ["Claude"]}
```

指定できるのは `"Claude"` と `"Codex"` です。ファイルを消すと自動判定に戻ります。

## 更新

```sh
cd ~/ai-usage-tools && git pull
```

macOS と Windows（WSL なし）は、次回の更新（1 分以内）から反映されます（トレイ本体の変更はサインインし直すか、トレイの「終了」→ `install.cmd` で反映）。
Windows（WSL）で `windows_tray/ai_usage_tray.ps1` が変わったときだけ、`install.sh` をもう一度実行してください。

## アンインストール

| 環境 | コマンド |
|---|---|
| macOS | `~/ai-usage-tools/macos_menubar/install.sh --uninstall`（SwiftBar ごと不要なら `brew uninstall --cask swiftbar`） |
| Windows（WSL なし） | `windows_tray\install.cmd -Uninstall` |
| Windows（WSL） | `~/ai-usage-tools/windows_tray/install.sh --uninstall` |

## データの扱い

- 読むもの（すべてその PC のローカル）
  - Claude: `~/.claude/.credentials.json`（Windows は `%USERPROFILE%\.claude\.credentials.json`、Mac は Keychain の `Claude Code-credentials`）、アカウント表示に `~/.claude.json`。環境変数 `CLAUDE_CONFIG_DIR` を設定していればそのフォルダの中を読みます（メニューバー／トレイの起動環境からも見える場所に設定してください）
  - Codex: インストール済みの Codex CLI に `codex app-server` で問い合わせます（ログインやトークン更新は Codex CLI 自身が行います）。CLI が無いときや失敗したときは `~/.codex/sessions/` の使用ログを読みます。アカウント表示の予備として `~/.codex/auth.json` も読みます
- 通信先は各サービスの本家だけです: `api.anthropic.com`（Claude の使用量。このツールが直接通信）、Codex は Codex CLI が `chatgpt.com` と通信します
- トークンの更新（リフレッシュ）はしません。ログイン情報を書き換えることはありません
- 保存するのは直近の使用量と通知済みフラグだけです（Mac: SwiftBar のプラグインデータフォルダ、Windows: `%LOCALAPPDATA%\ai-usage-tools`、WSL: `~/.cache/ai-usage-tools`）

## うまく表示されないとき

| 症状 | 原因と対処 |
|---|---|
| Claude が点線リング / `Token expired` | Claude Code のトークンは Claude Code 起動時にしか更新されません。Claude Code を一度起動してください |
| Codex のメニューに「最後に使った時点」と出る | Codex CLI から取得できず、使用ログの値を出しています。`codex` コマンドが使えるか、`codex login status` でログイン中かを確認してください（`Login expired` なら `codex login` し直し） |
| Codex の値がおかしい | `python3 codex_usage.py --raw` で Codex CLI の生のレスポンスを確認できます（メールアドレス等が含まれるので共有時は伏せてください） |
| Windows で `取得エラー` | トレイのメニューにエラー内容が出ます。Windows（WSL なし）なら `python windows_tray\usage_json.py`、WSL なら `python3 windows_tray/usage_json.py` を直接実行するとエラーが見られます |
| Windows でトレイが正しく動いているか知りたい | `%LOCALAPPDATA%\ai-usage-tools\tray_status.json` に、トレイ自身が最後に取得に成功した時刻（`last_success`）と直近のエラー（`last_error`）を書いています。インストール時もこれを見て動作確認しています |

## 仕組み

```
claude_usage.py ─┐
codex_usage.py ──┴─ usage_snapshot.py ─┬─ macos_menubar/ai_usage.1m.py   … SwiftBar プラグイン（Mac）
  （取得）           （キャッシュ・通知判定・  └─ windows_tray/usage_json.py      … JSON を出力
                       リング画像の描画）              └─ ai_usage_tray.ps1    … トレイに描くだけ（Windows / PowerShell）
```

Python は標準ライブラリだけで動きます（追加の pip install 不要）。

## 開発

```sh
python3 -m unittest discover -s tests -v   # 標準ライブラリのみ。ネットワークや実際のログインは使わない
```

GitHub Actions で、push のたびに Linux（Python 3.8 / 3.12）・macOS・Windows でテストし、シェルスクリプトと PowerShell スクリプトの構文・文字コードもチェックします。

## その他のツール

リポジトリには、作者が個人的に使っている以下のツールも入っています（上記のメニューバー／トレイ表示には不要）。

- `claude_monitor.py` — ターミナルに使用量を表示
- `claude_dashboard.py` — ブラウザで見るダッシュボード
- `claude_widget.py` / `clock_widget.py` — Linux（WSLg）向けのデスクトップウィジェット
- `usage_display/` — Raspberry Pi Pico + TFT 液晶で常時表示するガジェット

## ライセンス

[MIT](LICENSE)
