#!/usr/bin/env python3
"""Codex usage — 5h (primary) / weekly (secondary) rate-limit utilization.

Asks the locally installed Codex CLI through `codex app-server` (JSON-RPC over stdio):
`account/rateLimits/read` for the limits and `account/read` for the account. Codex itself
handles login and token refresh there, so this keeps working as long as Codex is logged in.
When the CLI is missing or the request fails, falls back to the latest `rate_limits`
snapshot Codex CLI writes into ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl, which is
as of the last Codex use.

Run `python3 codex_usage.py --raw` to dump the app-server responses.
"""

from __future__ import annotations

import base64
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
SESSIONS_DIR = CODEX_HOME / "sessions"
AUTH_PATH = CODEX_HOME / "auth.json"
TAIL_BYTES = 512 * 1024
APP_SERVER_TIMEOUT = 30  # seconds for the whole app-server session
# Menu bar / tray launchers run with a minimal PATH, so also look where Codex is usually installed
EXTRA_BIN_DIRS = [Path.home() / ".local" / "bin", Path("/opt/homebrew/bin"), Path("/usr/local/bin"),
                  Path.home() / ".npm-global" / "bin",
                  Path(os.environ.get("APPDATA") or Path.home()) / "npm",
                  *sorted(Path.home().glob(".nvm/versions/node/*/bin"), reverse=True)]

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


def _plan_label(plan) -> str | None:
    return plan.replace("_", " ").title() if plan and plan != "unknown" else None


def load_account() -> dict | None:
    """Return {"email", "plan"} from the ID token claims in auth.json (decoded locally, not verified).

    Used when the app-server is unavailable; the app-server's `account/read` is preferred.
    """
    try:
        with open(AUTH_PATH) as f:
            payload = json.load(f)["tokens"]["id_token"].split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None
    if not claims.get("email"):
        return None
    plan = (claims.get("https://api.openai.com/auth") or {}).get("chatgpt_plan_type")
    return {"email": claims["email"], "plan": _plan_label(plan)}


# ---------------------------------------------------------------- codex app-server

def _search_path() -> str:
    return os.pathsep.join([os.environ.get("PATH", "")] + [str(d) for d in EXTRA_BIN_DIRS])


def find_codex() -> str | None:
    return shutil.which("codex", path=_search_path())


def app_server_call(requests: list[tuple[str, dict | None]]) -> list[dict]:
    """Run `codex app-server`, perform the initialize handshake, send each (method, params)
    request and return the raw JSON-RPC responses in the same order."""
    exe = find_codex()
    if not exe:
        raise CodexUsageError("Codex CLI not found")
    # An npm-installed codex is a `#!/usr/bin/env node` script; node normally sits next to it
    env = dict(os.environ, PATH=os.pathsep.join([str(Path(exe).parent), _search_path()]))
    kwargs = {"env": env}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # no console flash from the tray
    try:
        proc = subprocess.Popen([exe, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, encoding="utf-8", **kwargs)
    except OSError as e:
        raise CodexUsageError(f"Could not start Codex CLI: {e}")

    lines: queue.Queue = queue.Queue()

    def reader():  # readline() can't time out portably (no select() on Windows pipes)
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=reader, daemon=True).start()
    deadline = time.monotonic() + APP_SERVER_TIMEOUT

    def send(msg: dict):
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()

    def wait_for(msg_id: int) -> dict:
        while True:
            try:
                line = lines.get(timeout=max(0.0, deadline - time.monotonic()))
            except queue.Empty:
                raise CodexUsageError("Codex app-server timed out")
            if line is None:
                raise CodexUsageError("Codex app-server exited unexpectedly")
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == msg_id and ("result" in msg or "error" in msg):
                return msg  # anything else is a notification and is ignored

    try:
        send({"method": "initialize", "id": 0,
              "params": {"clientInfo": {"name": "ai-usage-tools", "version": "1.0"}}})
        init = wait_for(0)
        if "error" in init:
            raise CodexUsageError(f"Codex app-server initialize failed: {init['error'].get('message')}")
        send({"method": "initialized"})
        responses = []
        for i, (method, params) in enumerate(requests, start=1):
            msg = {"method": method, "id": i}
            if params is not None:
                msg["params"] = params
            send(msg)
            responses.append(wait_for(i))
        return responses
    except (OSError, ValueError) as e:  # broken pipe etc.
        raise CodexUsageError(f"Codex app-server error: {e}")
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def _error_text(resp: dict) -> str:
    message = str((resp.get("error") or {}).get("message", "unknown error"))
    if "401" in message or "token" in message.lower():
        return "Login expired — run `codex login` again."
    return message.splitlines()[0][:120]


def fetch_app_server() -> dict:
    """Same shape as the log-based result plus "account", from `codex app-server`."""
    limits_resp, account_resp = app_server_call([
        ("account/rateLimits/read", None),
        ("account/read", {}),
    ])
    if "error" in limits_resp:
        raise CodexUsageError(_error_text(limits_resp))
    snapshot = (limits_resp.get("result") or {}).get("rateLimits") or {}
    out = {}
    for key in ("primary", "secondary"):
        w = snapshot.get(key)
        if isinstance(w, dict) and w.get("usedPercent") is not None:
            out[key] = {"used_percent": w["usedPercent"], "resets_at": w.get("resetsAt")}
    if "primary" not in out:
        raise CodexUsageError("Unexpected app-server response (see `codex_usage.py --raw`)")

    account = None
    acct = (account_resp.get("result") or {}).get("account") or {}
    if acct.get("email"):
        account = {"email": acct["email"], "plan": _plan_label(acct.get("planType"))}
    return {"rate_limits": out, "timestamp": datetime.now(timezone.utc), "source": "app-server",
            "account": account}


def fetch_usage() -> dict:
    """Return {"rate_limits", "timestamp", "source": "app-server" | "log", "account"?}.

    When the app-server fails and the logs are used, "live_error" holds the reason.
    """
    try:
        return fetch_app_server()
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
            for resp in app_server_call([("account/rateLimits/read", None), ("account/read", {})]):
                print(json.dumps(resp, indent=2, ensure_ascii=False))
        except CodexUsageError as e:
            sys.exit(str(e))
        return
    try:
        data = fetch_usage()
    except CodexUsageError as e:
        sys.exit(str(e))
    print(f"source: {data['source']}" + (f" (app-server failed: {data['live_error']})" if data.get("live_error") else ""))
    for w in get_windows(data):
        print(f"{w['label']:<13}: {w['pct']:3.0f}%  resets {w['resets_at']}")


if __name__ == "__main__":
    main()
