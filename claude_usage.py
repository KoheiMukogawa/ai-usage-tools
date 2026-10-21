#!/usr/bin/env python3
"""Claude Code usage monitor — shows session (5h) and weekly limit utilization in %.

Also used as a shared module by claude_dashboard.py / claude_widget.py / claude_monitor.py.
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
KEYCHAIN_SERVICE = "Claude Code-credentials"
CONFIG_PATH = Path.home() / ".claude.json"
BAR_WIDTH = 20

# (key, label) pairs in display order; opus/sonnet rows appear only when non-null
WINDOWS = [
    ("five_hour", "Session (5h)"),
    ("seven_day", "Weekly"),
    ("seven_day_opus", "Weekly (Opus)"),
    ("seven_day_sonnet", "Weekly (Sonnet)"),
]


class UsageError(Exception):
    pass


def _load_keychain_token() -> str | None:
    """On macOS, Claude Code keeps credentials in the Keychain instead of a file."""
    if sys.platform != "darwin":
        return None
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout
        return json.loads(out)["claudeAiOauth"]["accessToken"] or None
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError, KeyError, TypeError):
        return None


def load_access_token() -> str:
    if not CREDENTIALS_PATH.exists():
        token = _load_keychain_token()
        if token:
            return token
        where = f"Keychain ({KEYCHAIN_SERVICE})" if sys.platform == "darwin" else CREDENTIALS_PATH
        raise UsageError(f"Credentials not found: {where}\n"
                         "Log in with Claude Code first (`claude` then /login).")
    try:
        with open(CREDENTIALS_PATH) as f:
            creds = json.load(f)
        token = creds["claudeAiOauth"]["accessToken"]
    except (json.JSONDecodeError, KeyError, TypeError):
        raise UsageError(f"Unexpected credentials format in {CREDENTIALS_PATH}.\n"
                         "Launch Claude Code once to refresh your login.")
    if not token:
        raise UsageError("Empty access token — launch Claude Code once to refresh it.")
    return token


def load_account() -> dict | None:
    """Return {"email", "plan"} of the logged-in account from ~/.claude.json, or None."""
    try:
        with open(CONFIG_PATH) as f:
            account = json.load(f)["oauthAccount"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return None
    if not isinstance(account, dict) or not account.get("emailAddress"):
        return None
    org_type = account.get("organizationType") or ""
    plan = org_type[len("claude_"):] if org_type.startswith("claude_") else org_type
    plan = plan.replace("_", " ").title() or None
    return {"email": account["emailAddress"], "plan": plan}


def fetch_usage(token: str | None = None) -> dict:
    if token is None:
        token = load_access_token()
    req = urllib.request.Request(USAGE_URL, headers={
        "Authorization": f"Bearer {token}",
        "anthropic-beta": "oauth-2025-04-20",
        "User-Agent": "claude-code/2.1.174",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise UsageError("Token expired — launch Claude Code once to refresh it.")
        raise UsageError(f"API error: HTTP {e.code} {e.reason}")
    except urllib.error.URLError as e:
        raise UsageError(f"Network error: {e.reason}")


def get_windows(data: dict) -> list[dict]:
    """Normalize the API response into [{key, label, pct, resets_at}, ...]."""
    out = []
    for key, label in WINDOWS:
        w = data.get(key)
        if isinstance(w, dict) and w.get("utilization") is not None:
            out.append({
                "key": key,
                "label": label,
                "pct": float(w["utilization"]),
                "resets_at": w.get("resets_at"),
            })
    return out


def fmt_reset(iso_ts: str | None) -> str:
    if not iso_ts:
        return ""
    try:
        dt = datetime.fromisoformat(iso_ts).astimezone()
    except (ValueError, TypeError):
        return str(iso_ts)
    now = datetime.now().astimezone()
    if dt.date() == now.date():
        return dt.strftime("%H:%M")
    # %-m / %-d are glibc-only; build month/day by hand so Windows Python works too
    return f"{dt.strftime('%a')} {dt.month}/{dt.day} {dt.strftime('%H:%M')}"


def bar(pct: float, width: int = BAR_WIDTH) -> str:
    filled = round(pct / 100 * width)
    filled = max(0, min(width, filled))
    return "[" + "█" * filled + "░" * (width - filled) + "]"


def main():
    try:
        data = fetch_usage()
    except UsageError as e:
        sys.exit(str(e))

    windows = get_windows(data)
    if not windows:
        print("Unexpected response format — raw JSON:")
        print(json.dumps(data, indent=2))
        return

    width = max(len(w["label"]) for w in windows)
    for w in windows:
        line = f"{w['label']:<{width}} : {w['pct']:3.0f}%  {bar(w['pct'])}"
        reset = fmt_reset(w["resets_at"])
        if reset:
            line += f"  resets {reset}"
        print(line)


if __name__ == "__main__":
    main()
