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
import json
import math
import os
import struct
import subprocess
import sys
import zlib
from datetime import datetime, timedelta, timezone
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
DEPLETED_TRACK_RGBA = (255, 85, 85, 110)  # whole ring tinted red when nothing is left
STALE_ALPHA = 0.45                         # cached value shown while the fetch is failing
DASHES = 12                                # dashed ring = no data at all
LOW_REMAINING = 20

STATE_FILE = Path(os.environ.get("SWIFTBAR_PLUGIN_DATA_PATH")
                  or Path.home() / ".cache" / "ai-usage-tools") / "menubar_state.json"
CACHE_MAX_AGE = timedelta(hours=3)
NOTIFY_THRESHOLDS = (20, 5)  # notify when remaining % drops below these
NOTIFY_HYSTERESIS = 5        # re-arm once remaining climbs this far back above a threshold
WINDOW_NAMES = {
    "five_hour": "5時間枠", "seven_day": "週枠",
    "seven_day_opus": "週枠 (Opus)", "seven_day_sonnet": "週枠 (Sonnet)",
    "primary": "5時間枠", "secondary": "週枠",
}


def _sample_color(dx, dy, bands):
    """Return (rgb, alpha) of one sub-pixel sample, or None when it misses every band."""
    d = math.hypot(dx, dy)
    for r_out, r_in, frac, rgb, alpha, track, dashed in bands:
        if r_in <= d <= r_out:
            # angle measured clockwise from 12 o'clock, 0..1
            a = (math.atan2(dx, -dy) / (2 * math.pi)) % 1.0
            if dashed and (a * DASHES) % 1.0 > 0.55:
                return None
            if a < frac:
                return rgb, alpha
            return track[:3], track[3] / 255
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


def render_icon(gauges: list[tuple[float | None, float | None, tuple[int, int, int], bool]]) -> bytes:
    """Draw one double-ring gauge per (outer_pct, inner_pct, rgb, stale) side by side; return PNG bytes.

    A pct of None draws a dashed empty ring (no data); stale draws the arc faded.
    """
    w = (len(gauges) * GAUGE_PT + (len(gauges) - 1) * GAP_PT) * SCALE
    h = HEIGHT_PT * SCALE
    outer_out = GAUGE_PT * SCALE / 2 - 0.5
    outer_in = outer_out - OUTER_WIDTH_PT * SCALE
    inner_out = outer_in - RING_GAP_PT * SCALE
    inner_in = inner_out - INNER_WIDTH_PT * SCALE
    pixels = bytearray(w * h * 4)

    def band(r_out, r_in, pct, rgb, stale):
        if pct is None:
            return r_out, r_in, 0.0, rgb, 1.0, TRACK_RGBA, True
        frac = max(0.0, min(1.0, pct / 100))
        return (r_out, r_in, frac,
                LOW_RGB if pct < LOW_REMAINING else rgb,
                STALE_ALPHA if stale else 1.0,
                DEPLETED_TRACK_RGBA if pct <= 0 else TRACK_RGBA,
                False)

    for i, (outer_pct, inner_pct, rgb, stale) in enumerate(gauges):
        cx = (i * (GAUGE_PT + GAP_PT) + GAUGE_PT / 2) * SCALE
        _draw_gauge(pixels, w, h, cx, h / 2, [
            band(outer_out, outer_in, outer_pct, rgb, stale),
            band(inner_out, inner_in, inner_pct, rgb, stale),
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


def _load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
        return state if isinstance(state, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(state, f)
        tmp.replace(STATE_FILE)
    except OSError:
        pass


def _with_cache(state: dict, name: str, windows: list[dict], error: str | None):
    """Store fresh windows, or fall back to recent cached ones on error.

    Returns (windows, stale_since) where stale_since is the cache time when cached data is used.
    """
    cache = state.setdefault("cache", {})
    now = datetime.now(timezone.utc)
    if not error:
        cache[name] = {"windows": windows, "fetched_at": now.isoformat()}
        return windows, None
    entry = cache.get(name)
    if not entry:
        return [], None
    try:
        fetched = datetime.fromisoformat(entry["fetched_at"])
    except (KeyError, TypeError, ValueError):
        return [], None
    if now - fetched > CACHE_MAX_AGE:
        return [], None
    out = []
    for w in entry.get("windows", []):
        w = dict(w)
        try:
            if w.get("resets_at") and datetime.fromisoformat(w["resets_at"]) <= now:
                w["pct"], w["resets_at"] = 0.0, None  # window has reset since we cached it
        except (TypeError, ValueError):
            pass
        out.append(w)
    return out, fetched


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


def _check_notifications(state: dict, name: str, windows: list[dict]):
    notified = state.setdefault("notified", {})
    for w in windows:
        key = f"{name}:{w['key']}"
        left = max(0.0, 100 - w["pct"])
        done = {t for t in notified.get(key, []) if left < t + NOTIFY_HYSTERESIS}
        crossed = [t for t in NOTIFY_THRESHOLDS if left < t and t not in done]
        if crossed:
            reset = claude_usage.fmt_reset(w["resets_at"])
            body = f"{WINDOW_NAMES.get(w['key'], w['label'])}の残り {left:.0f}%"
            if reset:
                body += f"（{reset} リセット）"
            _notify(f"{name} の残量が少なくなっています", body)
            done.update(crossed)
        notified[key] = sorted(done)


def _remaining(windows: list[dict], key: str) -> float | None:
    for w in windows:
        if w["key"] == key:
            return max(0.0, 100 - w["pct"])
    return None


def _menu_rows(title: str, windows: list[dict], error: str | None, stale_since) -> list[str]:
    rows = [f"{title} | size=13"]
    if error and not windows:
        return rows + [f"{error} | color=#ff5555 size=12"]
    for w in windows:
        left = max(0.0, 100 - w["pct"])
        reset = claude_usage.fmt_reset(w["resets_at"])
        line = f"  {w['label']:<16} 残り {left:3.0f}%"
        if reset:
            line += f"   ({reset} リセット)"
        rows.append(f"{line} | font=Menlo size=12" + (" color=gray" if stale_since else ""))
    if stale_since:
        at = stale_since.astimezone().strftime("%H:%M")
        rows.append(f"  取得失敗のため {at} の値を表示中 | size=11 color=#e0a040")
        rows.append(f"  {error} | size=11 color=gray")
    return rows


def main():
    state = _load_state()

    claude, claude_err = [], None
    try:
        claude = claude_usage.get_windows(claude_usage.fetch_usage())
    except claude_usage.UsageError as e:
        claude_err = f"Claude: {str(e).splitlines()[0]}"
    codex_data = None
    codex, codex_err = [], None
    try:
        codex_data = codex_usage.fetch_usage()
        codex = codex_usage.get_windows(codex_data)
    except codex_usage.CodexUsageError as e:
        codex_err = f"Codex: {e}"

    claude, claude_stale = _with_cache(state, "Claude", claude, claude_err)
    codex, codex_stale = _with_cache(state, "Codex", codex, codex_err)
    if not claude_stale:
        _check_notifications(state, "Claude", claude)
    if not codex_stale:
        _check_notifications(state, "Codex", codex)
    _save_state(state)

    icon = base64.b64encode(render_icon([
        (_remaining(claude, "five_hour"), _remaining(claude, "seven_day"), CLAUDE_RGB, bool(claude_stale)),
        (_remaining(codex, "primary"), _remaining(codex, "secondary"), CODEX_RGB, bool(codex_stale)),
    ])).decode()

    print(f" | image={icon}")
    print("---")
    for row in _menu_rows("Claude", claude, claude_err, claude_stale):
        print(row)
    print("---")
    for row in _menu_rows("Codex", codex, codex_err, codex_stale):
        print(row)
    if codex_data and codex_data.get("timestamp"):
        mins = int((datetime.now(timezone.utc) - codex_data["timestamp"]).total_seconds() // 60)
        ago = f"{mins}分前" if mins < 60 else f"{mins // 60}時間前" if mins < 1440 else f"{mins // 1440}日前"
        print(f"  (Codexの値は最後に使った時点: {ago}) | size=11 color=gray")
    print("---")
    print(f"更新 {datetime.now().strftime('%H:%M')} | refresh=true")


if __name__ == "__main__":
    main()
