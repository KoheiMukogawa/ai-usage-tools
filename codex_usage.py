#!/usr/bin/env python3
"""Codex usage — 5h (primary) / weekly (secondary) rate-limit utilization.

Tries the live ChatGPT backend endpoint that Codex CLI's /status uses, with the
token from ~/.codex/auth.json. When that fails (no login, expired token — it is
refreshed only when Codex runs — or an unknown response shape), falls back to
the latest `rate_limits` snapshot Codex CLI writes into
~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl, which is as of the last Codex use.

Run `python3 codex_usage.py --raw` to dump the live response when the shape changes.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
SESSIONS_DIR = CODEX_HOME / "sessions"
AUTH_PATH = CODEX_HOME / "auth.json"
USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
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


def _load_auth() -> tuple[str, str | None]:
    try:
        with open(AUTH_PATH) as f:
            tokens = json.load(f)["tokens"]
        return tokens["access_token"], tokens.get("account_id")
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        raise CodexUsageError(f"No ChatGPT login in {AUTH_PATH}")


def load_account() -> dict | None:
    """Return {"email", "plan"} from the ID token claims in auth.json (decoded locally, not verified)."""
    try:
        with open(AUTH_PATH) as f:
            payload = json.load(f)["tokens"]["id_token"].split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None
    if not claims.get("email"):
        return None
    plan = (claims.get("https://api.openai.com/auth") or {}).get("chatgpt_plan_type")
    return {"email": claims["email"], "plan": plan.title() if plan else None}


def fetch_live_raw() -> dict:
    token, account_id = _load_auth()
    headers = {"Authorization": f"Bearer {token}", "User-Agent": "codex-cli"}
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id
    req = urllib.request.Request(USAGE_URL, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise CodexUsageError("Token expired — run Codex once to refresh it.")
        raise CodexUsageError(f"API error: HTTP {e.code} {e.reason}")
    except urllib.error.URLError as e:
        raise CodexUsageError(f"Network error: {e.reason}")
    except json.JSONDecodeError:
        raise CodexUsageError("Live usage response was not JSON")


def _live_window(w, now: datetime) -> dict | None:
    if not isinstance(w, dict) or w.get("used_percent") is None:
        return None
    resets = w.get("reset_at", w.get("resets_at"))
    if resets is None:
        after = w.get("reset_after_seconds", w.get("resets_in_seconds"))
        if after is not None:
            resets = now.timestamp() + after
    return {"used_percent": w["used_percent"], "resets_at": resets}


def fetch_live() -> dict:
    """Same shape as the log-based result, from the live endpoint."""
    body = fetch_live_raw()
    now = datetime.now(timezone.utc)
    limits = body.get("rate_limit") or body.get("rate_limits") or {}
    out = {}
    for key in ("primary", "secondary"):
        w = _live_window(limits.get(f"{key}_window", limits.get(key)), now)
        if w:
            out[key] = w
    if "primary" not in out:
        raise CodexUsageError("Unexpected live response shape (see `codex_usage.py --raw`)")
    return {"rate_limits": out, "timestamp": now, "source": "live"}


def fetch_usage() -> dict:
    """Return {"rate_limits": {...}, "timestamp": datetime | None, "source": "live" | "log"}.

    When the live fetch fails and the logs are used, "live_error" holds the reason.
    """
    try:
        return fetch_live()
    except CodexUsageError as live_e:
        try:
            data = fetch_log_usage()
        except CodexUsageError as log_e:
            raise CodexUsageError(f"{live_e} / {log_e}")
        data["live_error"] = str(live_e)
        return data


def fetch_log_usage() -> dict:
    """Return {"rate_limits": {...}, "timestamp": datetime | None, "source": "log"} from the newest log entry."""
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
                return {"rate_limits": limits, "timestamp": _parse_ts(entry.get("timestamp")),
                        "source": "log"}
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
    if "--raw" in sys.argv:
        try:
            print(json.dumps(fetch_live_raw(), indent=2, ensure_ascii=False))
        except CodexUsageError as e:
            sys.exit(str(e))
        return
    try:
        data = fetch_usage()
    except CodexUsageError as e:
        sys.exit(str(e))
    print(f"source: {data['source']}" + (f" (live failed: {data['live_error']})" if data.get("live_error") else ""))
    for w in get_windows(data):
        print(f"{w['label']:<13}: {w['pct']:3.0f}%  resets {w['resets_at']}")


if __name__ == "__main__":
    main()
