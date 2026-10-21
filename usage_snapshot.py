"""Shared core for the menu bar / tray gauges — fetch, cache, notification decisions, icon drawing.

Used by macos_menubar/ai_usage.1m.py (SwiftBar) and windows_tray/usage_json.py.
"""

from __future__ import annotations

import json
import math
import os
import struct
import sys
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import claude_usage
import codex_usage

# Double ring: outer = 5h window, inner = weekly window. Sizes are for an 18pt gauge
# and scale with the requested gauge size.
BASE_GAUGE_PT = 18
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

CACHE_MAX_AGE = timedelta(hours=3)
# Minimum seconds between real fetches; in between the last good values are reused as-is.
# Codex spawns `codex app-server` (~2s, plus its own network calls), so it is asked less often.
FETCH_INTERVAL = {"Claude": 0, "Codex": 290}
NOTIFY_THRESHOLDS = (20, 5)  # notify when remaining % drops below these
NOTIFY_HYSTERESIS = 5        # re-arm once remaining climbs this far back above a threshold
WINDOW_NAMES = {
    "five_hour": "5時間枠", "seven_day": "週枠",
    "seven_day_opus": "週枠 (Opus)", "seven_day_sonnet": "週枠 (Sonnet)",
    "primary": "5時間枠", "secondary": "週枠",
}

# (name, rgb, outer window key, inner window key), in display order
SERVICES = [
    ("Claude", CLAUDE_RGB, "five_hour", "seven_day"),
    ("Codex", CODEX_RGB, "primary", "secondary"),
]

# Optional {"services": ["Claude"]} to pin which services are shown instead of auto-detecting
CONFIG_FILE = Path(os.environ.get("APPDATA") or Path.home() / ".config") / "ai-usage-tools" / "config.json"


def _detected(name: str) -> bool:
    """Whether this machine has signs of being logged in to the service."""
    if name == "Claude":
        return (claude_usage.CREDENTIALS_PATH.exists() or claude_usage.CONFIG_PATH.exists()
                or (sys.platform == "darwin" and claude_usage._load_keychain_token() is not None))
    return codex_usage.AUTH_PATH.exists() or codex_usage.SESSIONS_DIR.exists()


def enabled_services() -> list[str]:
    """Services to show: the config file's list if present, else every detected one.

    Falls back to Claude alone (shown as a dashed "please log in" ring) when nothing is detected.
    """
    known = [name for name, *_ in SERVICES]
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            chosen = json.load(f).get("services")
        if isinstance(chosen, list) and any(name in chosen for name in known):
            return [name for name in known if name in chosen]
    except (OSError, ValueError, AttributeError):
        pass
    return [name for name in known if _detected(name)] or known[:1]


# ---------------------------------------------------------------- icon drawing

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


def render_icon(gauges: list[tuple[float | None, float | None, tuple[int, int, int], bool]],
                gauge_pt: float = 18, gap_pt: float = 5, height_pt: float = 18, scale: int = 2) -> bytes:
    """Draw one double-ring gauge per (outer_pct, inner_pct, rgb, stale) side by side; return PNG bytes.

    A pct of None draws a dashed empty ring (no data); stale draws the arc faded.
    The PNG is `scale`x pixels and tagged with a matching DPI so macOS sizes it in points.
    """
    k = gauge_pt / BASE_GAUGE_PT
    w = round((len(gauges) * gauge_pt + (len(gauges) - 1) * gap_pt) * scale)
    h = round(height_pt * scale)
    outer_out = gauge_pt * scale / 2 - 0.5
    outer_in = outer_out - OUTER_WIDTH_PT * k * scale
    inner_out = outer_in - RING_GAP_PT * k * scale
    inner_in = inner_out - INNER_WIDTH_PT * k * scale
    pixels = bytearray(w * h * 4)

    for i, (outer_pct, inner_pct, rgb, stale) in enumerate(gauges):
        cx = (i * (gauge_pt + gap_pt) + gauge_pt / 2) * scale
        _draw_gauge(pixels, w, h, cx, h / 2, [
            _band(outer_out, outer_in, outer_pct, rgb, stale),
            _band(inner_out, inner_in, inner_pct, rgb, stale),
        ])

    return _png(w, h, pixels, scale)


def _band(r_out, r_in, pct, rgb, stale):
    if pct is None:
        return r_out, r_in, 0.0, rgb, 1.0, TRACK_RGBA, True
    frac = max(0.0, min(1.0, pct / 100))
    return (r_out, r_in, frac,
            LOW_RGB if pct < LOW_REMAINING else rgb,
            STALE_ALPHA if stale else 1.0,
            DEPLETED_TRACK_RGBA if pct <= 0 else TRACK_RGBA,
            False)


def render_tray_pixels(outer_pct, inner_pct, rgb, stale, size: int) -> bytearray:
    """One double-ring gauge as size x size RGBA, pixel-snapped for tiny tray icons.

    Radii and ring widths are whole pixels and the centre sits on a pixel corner, so ring
    edges land on pixel boundaries instead of blurring across them (16px: 3 / 1 / 2 / hole 2).
    """
    outer_w = max(2, round(size * 0.19))
    gap_w = max(1, round(size * 0.06))
    inner_w = max(2, round(size * 0.14))
    outer_out = size / 2
    outer_in = outer_out - outer_w
    inner_out = outer_in - gap_w
    inner_in = inner_out - inner_w
    pixels = bytearray(size * size * 4)
    _draw_gauge(pixels, size, size, size / 2, size / 2, [
        _band(outer_out, outer_in, outer_pct, rgb, stale),
        _band(inner_out, inner_in, inner_pct, rgb, stale),
    ])
    return pixels


def render_ico(outer_pct, inner_pct, rgb, stale, sizes: list[int]) -> bytes:
    """A Windows .ico holding one pixel-snapped gauge per size (32bpp DIB entries with alpha)."""
    entries = []
    for size in sizes:
        rgba = render_tray_pixels(outer_pct, inner_pct, rgb, stale, size)
        bgra = bytearray()
        for y in range(size - 1, -1, -1):  # DIBs are stored bottom-up
            row = rgba[y * size * 4:(y + 1) * size * 4]
            for x in range(0, len(row), 4):
                bgra += bytes((row[x + 2], row[x + 1], row[x], row[x + 3]))
        mask = bytes(((size + 31) // 32) * 4 * size)  # AND mask unused with 32bpp alpha
        header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, len(bgra) + len(mask), 0, 0, 0, 0)
        entries.append((size, header + bytes(bgra) + mask))
    out = struct.pack("<HHH", 0, 1, len(entries))
    offset = 6 + 16 * len(entries)
    for size, data in entries:
        out += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    return out + b"".join(data for _, data in entries)


def _png(w: int, h: int, rgba: bytearray, scale: int = 1) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    raw = b"".join(b"\x00" + bytes(rgba[y * w * 4:(y + 1) * w * 4]) for y in range(h))
    ppm = round(72 * scale / 0.0254)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"pHYs", struct.pack(">IIB", ppm, ppm, 1))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


# ---------------------------------------------------------------- state (cache + notified flags)

def load_state(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(path: Path, state: dict):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
        tmp.replace(path)
    except OSError:
        pass


def _cached_windows(entry: dict, now: datetime) -> list[dict]:
    out = []
    for w in entry.get("windows", []):
        w = dict(w)
        try:
            if w.get("resets_at") and datetime.fromisoformat(w["resets_at"]) <= now:
                w["pct"], w["resets_at"] = 0.0, None  # window has reset since we cached it
        except (TypeError, ValueError):
            pass
        out.append(w)
    return out


def _cache_age(entry: dict | None, now: datetime) -> timedelta | None:
    try:
        return now - datetime.fromisoformat(entry["fetched_at"])
    except (KeyError, TypeError, ValueError):
        return None


def _with_cache(state: dict, name: str, windows: list[dict], error: str | None,
                note: str | None = None, account: dict | None = None):
    """Store fresh windows, or fall back to recent cached ones on error.

    Returns (windows, stale_since) where stale_since is the cache time when cached data is used.
    """
    cache = state.setdefault("cache", {})
    now = datetime.now(timezone.utc)
    if not error:
        cache[name] = {"windows": windows, "fetched_at": now.isoformat(), "note": note, "account": account}
        return windows, None
    entry = cache.get(name)
    age = _cache_age(entry, now)
    if age is None or age > CACHE_MAX_AGE:
        return [], None
    return _cached_windows(entry, now), now - age


def _check_notifications(state: dict, name: str, windows: list[dict]) -> list[tuple[str, str]]:
    """Return (title, body) alerts for newly crossed thresholds and record them as sent."""
    alerts = []
    notified = state.setdefault("notified", {})
    for w in windows:
        key = f"{name}:{w['key']}"
        left = remaining_of(w)
        done = {t for t in notified.get(key, []) if left < t + NOTIFY_HYSTERESIS}
        crossed = [t for t in NOTIFY_THRESHOLDS if left < t and t not in done]
        if crossed:
            reset = claude_usage.fmt_reset(w["resets_at"])
            body = f"{WINDOW_NAMES.get(w['key'], w['label'])}の残り {left:.0f}%"
            if reset:
                body += f"（{reset} リセット）"
            alerts.append((f"{name} の残量が少なくなっています", body))
            done.update(crossed)
        notified[key] = sorted(done)
    return alerts


# ---------------------------------------------------------------- snapshot

def remaining_of(w: dict) -> float:
    return max(0.0, 100 - w["pct"])


def _remaining(windows: list[dict], key: str) -> float | None:
    for w in windows:
        if w["key"] == key:
            return remaining_of(w)
    return None


def _ago(ts: datetime) -> str:
    mins = int((datetime.now(timezone.utc) - ts).total_seconds() // 60)
    if mins < 60:
        return f"{mins}分前"
    if mins < 1440:
        return f"{mins // 60}時間前"
    return f"{mins // 1440}日前"


def _fetch(name: str):
    """Return (windows, error, note, account, retry_after) for one service.

    account may be None; retry_after is set when the service asked us to back off.
    """
    try:
        if name == "Claude":
            return claude_usage.get_windows(claude_usage.fetch_usage()), None, None, None, None
        data = codex_usage.fetch_usage()
        note = None
        if data.get("source") == "log" and data.get("timestamp"):
            note = f"Codexの値は最後に使った時点: {_ago(data['timestamp'])}"
        return codex_usage.get_windows(data), None, note, data.get("account"), None
    except (claude_usage.UsageError, codex_usage.CodexUsageError) as e:
        return [], f"{name}: {str(e).splitlines()[0]}", None, None, getattr(e, "retry_after", None)


def _service_data(state: dict, name: str):
    """(windows, error, stale_since, note, account) for one service, honouring the polling
    interval and any rate-limit backoff before actually fetching."""
    now = datetime.now(timezone.utc)
    entry = state.get("cache", {}).get(name)
    backoff = state.setdefault("backoff", {}).get(name)
    try:
        backing_off = backoff and now < datetime.fromisoformat(backoff["until"])
    except (KeyError, TypeError, ValueError):
        backing_off = False

    if backing_off:
        until = datetime.fromisoformat(backoff["until"]).astimezone().strftime("%H:%M")
        error = f"{backoff['error']} — {until} に再開"
        windows, stale_since = _with_cache(state, name, [], error)
        return windows, error, stale_since, None, (entry or {}).get("account")

    age = _cache_age(entry, now)
    if age is not None and age.total_seconds() < FETCH_INTERVAL.get(name, 0):
        return _cached_windows(entry, now), None, None, entry.get("note"), entry.get("account")

    windows, error, note, account, retry_after = _fetch(name)
    if retry_after:
        state["backoff"][name] = {"until": (now + timedelta(seconds=retry_after)).isoformat(), "error": error}
    else:
        state["backoff"].pop(name, None)
    windows, stale_since = _with_cache(state, name, windows, error, note, account)
    return windows, error, stale_since, note, account


def _account(name: str, fetched: dict | None) -> str | None:
    """'user@example.com · Pro' for the account the service is logged in with.

    Uses the account returned with the usage (Codex app-server) when there is one,
    otherwise reads it from the service's local login files.
    """
    account = fetched or (claude_usage if name == "Claude" else codex_usage).load_account()
    if not account:
        return None
    return account["email"] + (f" · {account['plan']}" if account["plan"] else "")


def collect(state_path: Path) -> dict:
    """Fetch every service, apply the cache, decide notifications and persist the state.

    Returns {"services": [{name, rgb, account, windows, error, stale_since, note, outer, inner}],
             "alerts": [...]}
    """
    state = load_state(state_path)
    services, alerts = [], []
    enabled = enabled_services()
    for name, rgb, outer_key, inner_key in SERVICES:
        if name not in enabled:
            continue
        windows, error, stale_since, note, account = _service_data(state, name)
        if not stale_since:  # never alert from cached values
            alerts += _check_notifications(state, name, windows)
        services.append({
            "name": name, "rgb": rgb, "account": _account(name, account), "windows": windows, "error": error,
            "stale_since": stale_since, "note": note,
            "outer": _remaining(windows, outer_key), "inner": _remaining(windows, inner_key),
        })
    save_state(state_path, state)
    return {"services": services, "alerts": alerts}


def window_line(w: dict) -> str:
    """'Session (5h)     残り  81%   (00:00 リセット)' for menus."""
    line = f"{w['label']:<16} 残り {remaining_of(w):3.0f}%"
    reset = claude_usage.fmt_reset(w["resets_at"])
    if reset:
        line += f"   ({reset} リセット)"
    return line
