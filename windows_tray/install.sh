#!/bin/bash
# Windows のタスクトレイに AI 使用量を表示する。WSL 側から実行する。
#   ./windows_tray/install.sh              インストールして起動（ログオン時に自動起動）
#   ./windows_tray/install.sh --uninstall  停止して自動起動を解除
#   ./windows_tray/install.sh --install-codex  WSL に Codex CLI（公式の Linux 版単体バイナリ）を入れる
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
    # Node.js 不要の公式単体バイナリ。~/.local/bin は Ubuntu では PATH の先頭に入る
    url="https://github.com/openai/codex/releases/latest/download/codex-x86_64-unknown-linux-musl.tar.gz"
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT
    echo "==> Codex をダウンロード: $url"
    curl -fL --progress-bar "$url" -o "$tmp/codex.tar.gz"
    tar -xzf "$tmp/codex.tar.gz" -C "$tmp"
    mkdir -p "$HOME/.local/bin"
    install -m 755 "$tmp/codex-x86_64-unknown-linux-musl" "$HOME/.local/bin/codex"
    echo "==> インストール: $HOME/.local/bin/codex ($("$HOME/.local/bin/codex" --version))"
    case ":$PATH:" in
        *":$HOME/.local/bin:"*) ;;
        *) echo "    ~/.local/bin が PATH にありません。WSL を開き直すと有効になります。" ;;
    esac
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
cp ai_usage_tray.ps1 "$APP_DIR/"
printf 'CreateObject("WScript.Shell").Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""%s"" -Mode Wsl -Distro ""%s"" -Script ""%s""", 0, False\r\n' \
    "$TRAY_PS1_WIN" "$WSL_DISTRO_NAME" "$SCRIPT" | iconv -t UTF-16 > "$LAUNCHER"  # UTF-16 (BOM) so non-ASCII paths work
echo "==> インストール: $TRAY_PS1_WIN"
echo "==> 自動起動を登録: $(wslpath -w "$LAUNCHER")"

echo "Start-Process wscript.exe -ArgumentList '\"$(wslpath -w "$LAUNCHER")\"'" | run_ps
echo "==> 起動しました。ログイン中のサービスごとにタスクトレイにリングが表示されます。"
echo "    見当たらなければ、トレイの「^」の中を見るか、設定 → 個人用設定 → タスク バー →"
echo "    「その他のシステム トレイ アイコン」で Windows PowerShell をオンにしてください。"
