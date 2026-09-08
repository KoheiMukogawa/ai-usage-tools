#!/usr/bin/env python3
"""Claude usage terminal monitor — live-updating display for a terminal pane.

Usage:  python3 ~/claude_monitor.py [--once] [--interval SECONDS]
Press Ctrl+C to stop.
"""

import argparse
import sys
import time
from datetime import datetime

from claude_usage import UsageError, fetch_usage, fmt_reset, get_windows

BAR_WIDTH = 24

RESET = "\x1b[0m"
DIM = "\x1b[2m"
BOLD = "\x1b[1m"
RED = "\x1b[31m"
YELLOW = "\x1b[33m"
GREEN = "\x1b[32m"
CLEAR = "\x1b[2J\x1b[H"


def color(pct: float) -> str:
    if pct >= 80:
        return RED
    if pct >= 50:
        return YELLOW
    return GREEN


def braille_bar(pct: float, width: int = BAR_WIDTH) -> str:
    """Bar of braille cells: ⣿ = full cell, partial cells for the remainder."""
    cells = pct / 100 * width
    full = int(cells)
    frac = cells - full
    partials = ["", "⡀", "⡄", "⡆", "⡇", "⣇", "⣧", "⣷"]
    partial = partials[round(frac * 7)] if full < width else ""
    pad = width - full - (1 if partial else 0)
    return "⣿" * full + partial + DIM + "⠒" * pad + RESET


def render(windows: list[dict], error: str | None, interval: int) -> str:
    lines = [f"{BOLD}Claude Usage{RESET}", ""]
    if not windows:
        lines.append(error or "No data.")
    else:
        label_w = max(len(w["label"]) for w in windows)
        for w in windows:
            pct = w["pct"]
            col = color(pct)
            line = (f"  {w['label']:<{label_w}}  {col}{pct:3.0f}%{RESET}  "
                    f"{col}{braille_bar(pct)}{RESET}")
            reset = fmt_reset(w["resets_at"])
            if reset:
                line += f"  {DIM}resets {reset}{RESET}"
            lines.append(line)
        lines.append("")
        now = datetime.now().strftime("%H:%M:%S")
        status = f"{DIM}updated {now} · every {interval}s · Ctrl+C to quit{RESET}"
        if error:
            status += f"  {RED}(refresh failed — showing last data){RESET}"
        lines.append(status)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Claude usage terminal monitor")
    parser.add_argument("--once", action="store_true", help="Print once and exit")
    parser.add_argument("--interval", type=int, default=60, help="Refresh interval in seconds (default 60)")
    args = parser.parse_args()
    interval = max(30, args.interval)  # don't hammer the endpoint

    windows: list[dict] = []
    try:
        while True:
            error = None
            try:
                windows = get_windows(fetch_usage())
            except UsageError as e:
                error = str(e)
            if args.once:
                if error and not windows:
                    sys.exit(error)
                print(render(windows, error, interval))
                return
            print(CLEAR + render(windows, error, interval), flush=True)
            time.sleep(interval)
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
