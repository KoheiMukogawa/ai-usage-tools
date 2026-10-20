#!/usr/bin/env -S PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin python3
# <swiftbar.title>AI Usage</swiftbar.title>
# <swiftbar.desc>Claude / Codex remaining quota as ring gauges in the menu bar</swiftbar.desc>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
"""SwiftBar plugin — shows Claude and Codex 5h-window remaining % as ring gauges.

Install: symlink this file into the SwiftBar plugin folder (the `1m` in the
name is the refresh interval). It imports claude_usage / codex_usage from the
repository root, so keep it inside this repository.
"""

import base64
import math
import struct
import sys
import zlib
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import claude_usage  # noqa: E402
import codex_usage  # noqa: E402

# Menu bar icon is 18pt tall; drawn at 2x and tagged 144dpi so it stays sharp on Retina
SCALE = 2
RING_PT = 16
GAP_PT = 4
HEIGHT_PT = 18
RING_WIDTH_PT = 3.2
SUPERSAMPLE = 4

CLAUDE_RGB = (217, 119, 87)
CODEX_RGB = (90, 160, 255)
LOW_RGB = (255, 85, 85)
TRACK_RGBA = (128, 128, 128, 90)
LOW_REMAINING = 20


def _ring_coverage(px, py, cx, cy, r_out, r_in, frac):
    """Return (on_arc, on_track) sample counts for one pixel."""
    arc = track = 0
    n = SUPERSAMPLE
    for sy in range(n):
        for sx in range(n):
            dx = px + (sx + 0.5) / n - cx
            dy = py + (sy + 0.5) / n - cy
            d = math.hypot(dx, dy)
            if not (r_in <= d <= r_out):
                continue
            # angle measured clockwise from 12 o'clock, 0..1
            a = (math.atan2(dx, -dy) / (2 * math.pi)) % 1.0
            if a < frac:
                arc += 1
            else:
                track += 1
    return arc, track


def render_icon(remaining: list[tuple[float | None, tuple[int, int, int]]]) -> bytes:
    """Draw one ring per (remaining_pct, rgb) side by side and return PNG bytes."""
    w = (len(remaining) * RING_PT + (len(remaining) - 1) * GAP_PT) * SCALE
    h = HEIGHT_PT * SCALE
    r_out = RING_PT * SCALE / 2 - 0.5
    r_in = r_out - RING_WIDTH_PT * SCALE
    pixels = bytearray(w * h * 4)
    total = SUPERSAMPLE * SUPERSAMPLE

    for i, (pct, rgb) in enumerate(remaining):
        frac = 0.0 if pct is None else max(0.0, min(1.0, pct / 100))
        if pct is not None and pct < LOW_REMAINING:
            rgb = LOW_RGB
        cx = (i * (RING_PT + GAP_PT) + RING_PT / 2) * SCALE
        cy = h / 2
        x0, x1 = int(cx - r_out - 1), int(cx + r_out + 2)
        for py in range(h):
            for px in range(max(0, x0), min(w, x1)):
                arc, track = _ring_coverage(px, py, cx, cy, r_out, r_in, frac)
                if not arc and not track:
                    continue
                a_arc = arc / total
                a_track = track / total * TRACK_RGBA[3] / 255
                alpha = a_arc + a_track
                r = (rgb[0] * a_arc + TRACK_RGBA[0] * a_track) / alpha
                g = (rgb[1] * a_arc + TRACK_RGBA[1] * a_track) / alpha
                b = (rgb[2] * a_arc + TRACK_RGBA[2] * a_track) / alpha
                o = (py * w + px) * 4
                pixels[o:o + 4] = bytes((round(r), round(g), round(b), round(alpha * 255)))

    return _png(w, h, pixels)


def _png(w: int, h: int, rgba: bytearray) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    raw = b"".join(b"\x00" + bytes(rgba[y * w * 4:(y + 1) * w * 4]) for y in range(h))
    ppm = round(72 * SCALE / 0.0254)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"pHYs", struct.pack(">IIB", ppm, ppm, 1))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def _load(name: str, fetch, get_windows, errors):
    try:
        return get_windows(fetch()), None
    except errors as e:
        return [], f"{name}: {str(e).splitlines()[0]}"


def _remaining(windows: list[dict], key: str) -> float | None:
    for w in windows:
        if w["key"] == key:
            return max(0.0, 100 - w["pct"])
    return None


def _menu_rows(title: str, windows: list[dict], error: str | None) -> list[str]:
    rows = [f"{title} | size=13"]
    if error:
        return rows + [f"{error} | color=#ff5555 size=12"]
    for w in windows:
        left = max(0.0, 100 - w["pct"])
        reset = claude_usage.fmt_reset(w["resets_at"])
        line = f"  {w['label']:<16} 残り {left:3.0f}%"
        if reset:
            line += f"   ({reset} リセット)"
        rows.append(f"{line} | font=Menlo size=12")
    return rows


def main():
    claude, claude_err = _load("Claude", claude_usage.fetch_usage, claude_usage.get_windows,
                               claude_usage.UsageError)
    codex_data = None
    try:
        codex_data = codex_usage.fetch_usage()
        codex, codex_err = codex_usage.get_windows(codex_data), None
    except codex_usage.CodexUsageError as e:
        codex, codex_err = [], f"Codex: {e}"

    claude_left = _remaining(claude, "five_hour")
    codex_left = _remaining(codex, "primary")
    icon = base64.b64encode(render_icon([(claude_left, CLAUDE_RGB), (codex_left, CODEX_RGB)])).decode()
    title = " ".join("--" if v is None else f"{v:.0f}" for v in (claude_left, codex_left))

    print(f"{title} | image={icon} font=Menlo size=11")
    print("---")
    for row in _menu_rows("Claude", claude, claude_err):
        print(row)
    print("---")
    for row in _menu_rows("Codex", codex, codex_err):
        print(row)
    if codex_data and codex_data.get("timestamp"):
        mins = int((datetime.now(timezone.utc) - codex_data["timestamp"]).total_seconds() // 60)
        ago = f"{mins}分前" if mins < 60 else f"{mins // 60}時間前" if mins < 1440 else f"{mins // 1440}日前"
        print(f"  (Codexの値は最後に使った時点: {ago}) | size=11 color=gray")
    print("---")
    print(f"更新 {datetime.now().strftime('%H:%M')} | refresh=true")


if __name__ == "__main__":
    main()
