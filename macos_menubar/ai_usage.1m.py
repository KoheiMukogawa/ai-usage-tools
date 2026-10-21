#!/usr/bin/env -S PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin python3
# <swiftbar.title>AI Usage</swiftbar.title>
# <swiftbar.desc>Claude / Codex remaining quota as double-ring gauges in the menu bar</swiftbar.desc>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
"""SwiftBar plugin — shows Claude and Codex remaining % as double-ring gauges (outer 5h, inner weekly).

Install: symlink this file into the SwiftBar plugin folder (the `1m` in the
name is the refresh interval). It imports usage_snapshot (and through it claude_usage /
codex_usage) from the repository root, so keep it inside this repository.
"""

import base64
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import usage_snapshot as us  # noqa: E402

STATE_FILE = Path(os.environ.get("SWIFTBAR_PLUGIN_DATA_PATH")
                  or Path.home() / ".cache" / "ai-usage-tools") / "menubar_state.json"


def _notify(title: str, body: str):
    if sys.platform != "darwin":
        return
    script = ('on run argv\n'
              'display notification (item 2 of argv) with title (item 1 of argv) sound name "default"\n'
              'end run')
    try:
        subprocess.run(["osascript", "-e", script, title, body],
                       capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def _menu_rows(svc: dict) -> list[str]:
    rows = [f"{svc['name']} | size=13"]
    if svc["account"]:
        rows.append(f"  {svc['account']} | size=11 color=gray")
    windows, error, stale_since = svc["windows"], svc["error"], svc["stale_since"]
    if error and not windows:
        return rows + [f"{error} | color=#ff5555 size=12"]
    for w in windows:
        rows.append(f"  {us.window_line(w)} | font=Menlo size=12" + (" color=gray" if stale_since else ""))
    if stale_since:
        at = stale_since.astimezone().strftime("%H:%M")
        rows.append(f"  取得失敗のため {at} の値を表示中 | size=11 color=#e0a040")
        rows.append(f"  {error} | size=11 color=gray")
    if svc["note"]:
        rows.append(f"  ({svc['note']}) | size=11 color=gray")
    return rows


def main():
    snap = us.collect(STATE_FILE)
    for title, body in snap["alerts"]:
        _notify(title, body)

    icon = base64.b64encode(us.render_icon([
        (s["outer"], s["inner"], s["rgb"], bool(s["stale_since"])) for s in snap["services"]
    ])).decode()

    print(f" | image={icon}")
    for svc in snap["services"]:
        print("---")
        for row in _menu_rows(svc):
            print(row)
    print("---")
    print(f"更新 {datetime.now().strftime('%H:%M')} | refresh=true")


if __name__ == "__main__":
    main()
