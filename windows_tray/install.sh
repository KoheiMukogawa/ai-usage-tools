#!/bin/bash
# Windows のタスクトレイに AI 使用量を表示する。WSL 側から実行する。
#   ./windows_tray/install.sh              インストールして起動（ログオン時に自動起動）
#   ./windows_tray/install.sh --uninstall  停止して自動起動を解除
#   ./windows_tray/install.sh --install-codex  WSL に Codex CLI を公式インストーラーで入れる
# ai_usage_tray.ps1 を %LOCALAPPDATA%\ai-usage-tools にコピーし、スタートアップに
# 非表示で起動するランチャー (.vbs) を置く。ps1 を変更したら再実行すること。
set -euo pipefail

cd "$(dirname "$0")"
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe

if [ ! -x "$PS" ] || [ -z "${WSL_DISTRO_NAME:-}" ]; then
    echo "WSL の中から実行してください。" >&2
    exit 1
fi

if [ "${1:-}" = "--install-codex" ]; then
    # OpenAI 公式の単体インストーラー（Node.js 不要）。実行ファイルだけでなく付属ファイル一式を
    # ~/.codex/packages/standalone に入れ、~/.local/bin/codex にリンクする（単体バイナリだけだと
    # 対話画面が "no complete local package" で起動しない）
    url="https://github.com/openai/codex/releases/latest/download/install.sh"
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT
    echo "==> Codex 公式インストーラーを取得: $url"
    curl -fsSL "$url" -o "$tmp/install.sh"
    CODEX_NON_INTERACTIVE=1 sh "$tmp/install.sh"
    echo "    続けて \`codex login --device-auth\` でログインしてください。"
    exit 0
fi

# Run PowerShell code passed on stdin (encoded, so no shell quoting issues)
run_ps() {
    local code
    code="\$ProgressPreference = 'SilentlyContinue'"$'\n'"$(cat)"
    "$PS" -NoProfile -NonInteractive -EncodedCommand "$(printf '%s' "$code" | iconv -t UTF-16LE | base64 -w0)" \
        < /dev/null | tr -d '\r'
}

APP_DIR_WIN="$(echo '[Environment]::GetFolderPath("LocalApplicationData")' | run_ps)\\ai-usage-tools"
STARTUP_WIN="$(echo '[Environment]::GetFolderPath("Startup")' | run_ps)"
APP_DIR="$(wslpath -u "$APP_DIR_WIN")"
LAUNCHER="$(wslpath -u "$STARTUP_WIN")/AI Usage Tray.vbs"
TRAY_PS1_WIN="$APP_DIR_WIN\\ai_usage_tray.ps1"
SCRIPT="$(realpath usage_json.py)"

stop_tray() {
    run_ps <<'EOF'
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
    Where-Object { $_.CommandLine -like '*ai_usage_tray.ps1*' } |
    ForEach-Object { Invoke-CimMethod -InputObject $_ -MethodName Terminate | Out-Null }
EOF
}

if [ "${1:-}" = "--uninstall" ]; then
    stop_tray
    rm -f "$LAUNCHER"
    rm -rf "$APP_DIR"
    echo "==> 停止して自動起動を解除しました。"
    exit 0
fi

echo "==> 事前チェック"
if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 が見つかりません。sudo apt install python3 で入れてください。" >&2
    exit 1
fi
if [ ! -f "$HOME/.claude/.credentials.json" ]; then
    echo "    - Claude Code: 未検出（claude を起動して /login すると自動で表示されます）"
fi
if [ ! -f "${CODEX_HOME:-$HOME/.codex}/auth.json" ]; then
    echo "    - Codex: 未検出（./windows_tray/install.sh --install-codex → codex login --device-auth で"
    echo "      使い始めると自動で表示されます）"
fi
python3 "$SCRIPT" > /dev/null

stop_tray
mkdir -p "$APP_DIR"
STATUS="$APP_DIR/tray_status.json"
rm -f "$STATUS"  # the tray rewrites it; a fresh last_success proves the tray itself works
cp ai_usage_tray.ps1 "$APP_DIR/"
printf 'CreateObject("WScript.Shell").Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""%s"" -Mode Wsl -Distro ""%s"" -Script ""%s""", 0, False\r\n' \
    "$TRAY_PS1_WIN" "$WSL_DISTRO_NAME" "$SCRIPT" | iconv -t UTF-16 > "$LAUNCHER"  # UTF-16 (BOM) so non-ASCII paths work
echo "==> インストール: $TRAY_PS1_WIN"
echo "==> 自動起動を登録: $(wslpath -w "$LAUNCHER")"

echo "Start-Process wscript.exe -ArgumentList '\"$(wslpath -w "$LAUNCHER")\"'" | run_ps
echo "==> 起動しました。トレイの最初の取得を待っています..."

# The tray writes tray_status.json after every fetch (see ai_usage_tray.ps1)
for _ in $(seq 1 45); do
    sleep 1
    [ -f "$STATUS" ] || continue
    result="$(python3 - "$STATUS" <<'EOF'
import json, sys
try:
    status = json.load(open(sys.argv[1], encoding="utf-8-sig"))
except (OSError, ValueError):
    sys.exit(0)
if status.get("last_success"):
    print("ok")
elif status.get("last_error"):
    print("error:" + status["last_error"])
EOF
)"
    case "$result" in
        ok)
            echo "==> 動作確認OK: トレイが使用量の取得に成功しました。"
            echo "    ログイン中のサービスごとにタスクトレイにリングが表示されます。見当たらなければ、トレイの「^」の中を"
            echo "    見るか、設定 → 個人用設定 → タスク バー →「その他のシステム トレイ アイコン」で Windows PowerShell をオンに。"
            exit 0
            ;;
        error:*)
            echo "!! トレイが取得に失敗しました: ${result#error:}" >&2
            echo "   状態ファイル: $(wslpath -w "$STATUS")" >&2
            exit 1
            ;;
    esac
done
echo "!! 45 秒待ってもトレイから応答がありません。状態ファイル: $(wslpath -w "$STATUS")" >&2
exit 1
