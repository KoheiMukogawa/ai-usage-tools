#!/usr/bin/env python3
"""WSL-side helper for the Windows tray app — prints one JSON snapshot to stdout.

ai_usage_tray.ps1 runs this every minute through `wsl.exe` and only draws what it
gets: one double-ring icon per service (.ico with several sizes, base64), tooltip, menu lines and alerts.
All UI text lives here so the PowerShell script can stay ASCII-only (Windows
PowerShell 5.1 misreads BOM-less UTF-8 scripts).

Usage: python3 usage_json.py [--size PX]   (PX = tray icon size, default 16; also included in the .ico)
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import usage_snapshot as us  # noqa: E402

# Windows Python: %LOCALAPPDATA%\ai-usage-tools (removed by install.ps1 -Uninstall); WSL: ~/.cache
STATE_FILE = (Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache")
              / "ai-usage-tools" / "tray_state.json")
SHORT_NAMES = {"five_hour": "5h", "seven_day": "週", "primary": "5h", "secondary": "週"}


def _tooltip(svc: dict) -> str:
    if svc["error"] and not svc["windows"]:
        return f"{svc['name']}: 取得エラー"
    parts = [f"{SHORT_NAMES[w['key']]} 残り{us.remaining_of(w):.0f}%"
             for w in svc["windows"] if w["key"] in SHORT_NAMES]
    text = f"{svc['name']}  " + " / ".join(parts)
    if svc["stale_since"]:
        text += "（前回値）"
    return text


def _lines(svc: dict) -> list[str]:
    windows, error, stale_since = svc["windows"], svc["error"], svc["stale_since"]
    if error and not windows:
        return [error]
    lines = []
    for w in windows:
        line = f"{us.WINDOW_NAMES.get(w['key'], w['label'])}  残り {us.remaining_of(w):.0f}%"
        reset = us.claude_usage.fmt_reset(w["resets_at"])
        if reset:
            line += f"（{reset} リセット）"
        lines.append(line)
    if stale_since:
        lines.append(f"取得失敗のため {stale_since.astimezone().strftime('%H:%M')} の値を表示中")
        lines.append(error)
    if svc["note"]:
        lines.append(svc["note"])
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=16)
    size = ap.parse_args().size

    snap = us.collect(STATE_FILE)
    out = {
        "services": [{
            "name": s["name"],
            "icon": base64.b64encode(us.render_ico(
                s["outer"], s["inner"], s["rgb"], bool(s["stale_since"]),
                sorted({16, 20, 24, 32, size}))).decode(),
            "account": s["account"],
            "tooltip": _tooltip(s),
            "lines": _lines(s),
        } for s in snap["services"]],
        "alerts": [{"title": t, "body": b} for t, b in snap["alerts"]],
        "updated": datetime.now().strftime("%H:%M"),
        "labels": {"refresh": "今すぐ更新", "quit": "終了", "updated": "更新"},
    }
    json.dump(out, sys.stdout, ensure_ascii=True)


if __name__ == "__main__":
    main()
