#!/usr/bin/env python3
"""Codex usage — reads the latest rate-limit snapshot from Codex CLI session logs.

Codex CLI writes `rate_limits` (5h primary / weekly secondary) into
~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl on every turn, so the values are
as of the last Codex use, not live.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
SESSIONS_DIR = CODEX_HOME / "sessions"
TAIL_BYTES = 512 * 1024

# (key, label) pairs in display order
WINDOWS = [
    ("primary", "Session (5h)"),
    ("secondary", "Weekly"),
]


class CodexUsageError(Exception):
    pass


def _latest_logs(limit: int = 20) -> list[Path]:
    # Directory names sort chronologically; take the newest by name, then order by mtime
    files = sorted(SESSIONS_DIR.glob("*/*/*/rollout-*.jsonl"), reverse=True)[:limit]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def _read_lines_from_end(path: Path) -> list[str]:
    size = path.stat().st_size
    with open(path, "rb") as f:
        if size > TAIL_BYTES:
            f.seek(size - TAIL_BYTES)
            f.readline()  # drop the partial first line
        return f.read().decode("utf-8", errors="replace").splitlines()[::-1]


def _parse_ts(value) -> datetime | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def fetch_usage() -> dict:
    """Return {"rate_limits": {...}, "timestamp": datetime | None} from the newest log entry."""
    if not SESSIONS_DIR.exists():
        raise CodexUsageError(f"Codex sessions not found: {SESSIONS_DIR}")
    for path in _latest_logs():
        for line in _read_lines_from_end(path):
            if '"rate_limits"' not in line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            limits = (entry.get("payload") or {}).get("rate_limits")
            if isinstance(limits, dict) and limits.get("primary"):
                return {"rate_limits": limits, "timestamp": _parse_ts(entry.get("timestamp"))}
    raise CodexUsageError("No rate-limit data in Codex logs yet — use Codex once.")


def get_windows(data: dict) -> list[dict]:
    """Normalize into [{key, label, pct, resets_at}, ...] like claude_usage.get_windows.

    A window whose reset time has already passed is reported as 0% used with no reset time.
    """
    now = datetime.now(timezone.utc)
    logged_at = data.get("timestamp") or now
    out = []
    for key, label in WINDOWS:
        w = data["rate_limits"].get(key)
        if not isinstance(w, dict) or w.get("used_percent") is None:
            continue
        resets = _parse_ts(w.get("resets_at"))
        if resets is None and w.get("resets_in_seconds") is not None:  # older Codex versions
            resets = datetime.fromtimestamp(logged_at.timestamp() + w["resets_in_seconds"], tz=timezone.utc)
        pct = float(w["used_percent"])
        if resets is not None and resets <= now:
            pct, resets = 0.0, None
        out.append({
            "key": key,
            "label": label,
            "pct": pct,
            "resets_at": resets.isoformat() if resets else None,
        })
    return out


def main():
    try:
        data = fetch_usage()
    except CodexUsageError as e:
        sys.exit(str(e))
    for w in get_windows(data):
        print(f"{w['label']:<13}: {w['pct']:3.0f}%  resets {w['resets_at']}")


if __name__ == "__main__":
    main()
