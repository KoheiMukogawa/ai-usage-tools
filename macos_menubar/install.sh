#!/bin/bash
# Mac メニューバーの AI 使用量表示をセットアップする。
#   使い方: ./macos_menubar/install.sh
# Homebrew の python3 と SwiftBar を入れ、プラグインを SwiftBar のプラグインフォルダへリンクする。
set -euo pipefail

cd "$(dirname "$0")"
PLUGIN="$PWD/ai_usage.1m.py"
SWIFTBAR_DOMAIN="com.ameba.SwiftBar"

if [ "$(uname)" != "Darwin" ]; then
    echo "このスクリプトは macOS 用です。" >&2
    exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
    echo "Homebrew が見つかりません。先に https://brew.sh の手順でインストールしてください。" >&2
    exit 1
fi

if [ ! -x /opt/homebrew/bin/python3 ] && [ ! -x /usr/local/bin/python3 ]; then
    echo "==> python3 をインストール"
    brew install python
fi

if [ ! -d /Applications/SwiftBar.app ] && [ ! -d "$HOME/Applications/SwiftBar.app" ]; then
    echo "==> SwiftBar をインストール"
    brew install --cask swiftbar
fi

PLUGIN_DIR="$(defaults read "$SWIFTBAR_DOMAIN" PluginDirectory 2>/dev/null || true)"
if [ -z "$PLUGIN_DIR" ]; then
    PLUGIN_DIR="$HOME/SwiftBarPlugins"
    defaults write "$SWIFTBAR_DOMAIN" PluginDirectory "$PLUGIN_DIR"
fi
PLUGIN_DIR="${PLUGIN_DIR/#\~/$HOME}"
mkdir -p "$PLUGIN_DIR"

chmod +x "$PLUGIN"
ln -sf "$PLUGIN" "$PLUGIN_DIR/ai_usage.1m.py"
echo "==> プラグインをリンク: $PLUGIN_DIR/ai_usage.1m.py"

# 一度ここで実行して動作確認する（Keychain の許可ダイアログが出たら「常に許可」）
echo "==> 動作確認"
"$PLUGIN" | sed -e 's/image=[^ ]*/image=<icon>/' -e '/^---$/d'

open -a SwiftBar
open "swiftbar://refreshallplugins" 2>/dev/null || true
echo "==> 完了。メニューバーにリングが表示されます。"
