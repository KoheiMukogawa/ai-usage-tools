#!/usr/bin/env -S PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin python3
# <swiftbar.title>AI Usage</swiftbar.title>
# <swiftbar.desc>Claude / Codex remaining quota as double-ring gauges in the menu bar</swiftbar.desc>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
"""SwiftBar plugin — shows Claude and Codex remaining % as double-ring gauges (outer 5h, inner weekly).

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
GAUGE_PT = 18
GAP_PT = 5
HEIGHT_PT = 18
# Double ring: outer = 5h window, inner = weekly window
OUTER_WIDTH_PT = 2.8
RING_GAP_PT = 1.2
INNER_WIDTH_PT = 2.8
SUPERSAMPLE = 4

CLAUDE_RGB = (217, 119, 87)   # Claude brand orange #D97757
CODEX_RGB = (16, 163, 127)    # ChatGPT green #10A37F (Codex has no brand accent of its own)
LOW_RGB = (255, 85, 85)
TRACK_RGBA = (128, 128, 128, 90)
LOW_REMAINING = 20


def _sample_color(dx, dy, bands):
    """Return (rgb, alpha) of one sub-pixel sample, or None when it misses every band."""
    d = math.hypot(dx, dy)
    for r_out, r_in, frac, rgb in bands:
        if r_in <= d <= r_out:
            # angle measured clockwise from 12 o'clock, 0..1
            a = (math.atan2(dx, -dy) / (2 * math.pi)) % 1.0
            if a < frac:
                return rgb, 1.0
            return TRACK_RGBA[:3], TRACK_RGBA[3] / 255
    return None


def _draw_gauge(pixels, w, h, cx, cy, bands):
    r_max = bands[0][0]
    n = SUPERSAMPLE
    total = n * n
    for py in range(h):
        for px in range(max(0, int(cx - r_max - 1)), min(w, int(cx + r_max + 2))):
            sr = sg = sb = sa = 0.0
            for sy in range(n):
                for sx in range(n):
                    hit = _sample_color(px + (sx + 0.5) / n - cx, py + (sy + 0.5) / n - cy, bands)
                    if hit:
                        (r, g, b), a = hit
                        sr, sg, sb, sa = sr + r * a, sg + g * a, sb + b * a, sa + a
            if sa:
                o = (py * w + px) * 4
                pixels[o:o + 4] = bytes((round(sr / sa), round(sg / sa), round(sb / sa),
                                         round(sa / total * 255)))


def render_icon(gauges: list[tuple[float | None, float | None, tuple[int, int, int]]]) -> bytes:
    """Draw one double-ring gauge per (outer_pct, inner_pct, rgb) side by side; return PNG bytes."""
    w = (len(gauges) * GAUGE_PT + (len(gauges) - 1) * GAP_PT) * SCALE
    h = HEIGHT_PT * SCALE
    outer_out = GAUGE_PT * SCALE / 2 - 0.5
    outer_in = outer_out - OUTER_WIDTH_PT * SCALE
    inner_out = outer_in - RING_GAP_PT * SCALE
    inner_in = inner_out - INNER_WIDTH_PT * SCALE
    pixels = bytearray(w * h * 4)

    def band(r_out, r_in, pct, rgb):
        frac = 0.0 if pct is None else max(0.0, min(1.0, pct / 100))
        return r_out, r_in, frac, LOW_RGB if pct is not None and pct < LOW_REMAINING else rgb

    for i, (outer_pct, inner_pct, rgb) in enumerate(gauges):
        cx = (i * (GAUGE_PT + GAP_PT) + GAUGE_PT / 2) * SCALE
        _draw_gauge(pixels, w, h, cx, h / 2, [
            band(outer_out, outer_in, outer_pct, rgb),
            band(inner_out, inner_in, inner_pct, rgb),
        ])

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

    icon = base64.b64encode(render_icon([
        (_remaining(claude, "five_hour"), _remaining(claude, "seven_day"), CLAUDE_RGB),
        (_remaining(codex, "primary"), _remaining(codex, "secondary"), CODEX_RGB),
    ])).decode()

    print(f" | image={icon}")
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
