"""Tests for the shared core (stdlib unittest only; no network, no real logins).

Run from the repository root:  python3 -m unittest discover -s tests -v
"""

import base64
import io
import json
import os
import shutil
import struct
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "windows_tray"))

import claude_usage  # noqa: E402
import codex_usage  # noqa: E402
import usage_snapshot as us  # noqa: E402
import usage_json  # noqa: E402

FUTURE = 1893456000  # 2030-01-01, always in the future for these tests


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


# ---------------------------------------------------------------- Claude

class ClaudeTest(TempDirTest):
    def test_load_account_reads_utf8_with_non_ascii(self):
        # Windows Python opens files as cp932 by default; this used to crash the whole snapshot
        cfg = self.tmp / ".claude.json"
        cfg.write_text(json.dumps({"projects": {"C:/作業": {}}, "oauthAccount": {
            "emailAddress": "a@example.com", "organizationType": "claude_max"}}, ensure_ascii=False),
            encoding="utf-8")
        with mock.patch.object(claude_usage, "CONFIG_PATH", cfg):
            self.assertEqual(claude_usage.load_account(), {"email": "a@example.com", "plan": "Max"})

    def test_load_account_tolerates_broken_file(self):
        cfg = self.tmp / ".claude.json"
        cfg.write_bytes(b"\xff\xfe not json")
        with mock.patch.object(claude_usage, "CONFIG_PATH", cfg):
            self.assertIsNone(claude_usage.load_account())

    def test_fmt_reset_has_no_glibc_only_codes(self):
        # %-m / %-d raise on Windows; the output must be built portably
        ts = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        out = claude_usage.fmt_reset(ts)
        self.assertRegex(out, r"^\w{3} \d{1,2}/\d{1,2} \d{2}:\d{2}$")

    def test_get_windows_skips_null_windows(self):
        data = {"five_hour": {"utilization": 12.0, "resets_at": None}, "seven_day_opus": None}
        self.assertEqual([w["key"] for w in claude_usage.get_windows(data)], ["five_hour"])


# ---------------------------------------------------------------- Codex

class CodexLogTest(TempDirTest):
    def write_log(self, line: dict):
        d = self.tmp / "sessions" / "2026" / "10" / "21"
        d.mkdir(parents=True)
        (d / "rollout-x.jsonl").write_text("not json\n" + json.dumps(line) + "\n", encoding="utf-8")

    def test_reads_latest_rate_limits(self):
        self.write_log({"timestamp": "2026-10-21T00:00:00Z", "payload": {"rate_limits": {
            "primary": {"used_percent": 30, "resets_at": FUTURE},
            "secondary": {"used_percent": 90, "resets_at": FUTURE}}}})
        with mock.patch.object(codex_usage, "SESSIONS_DIR", self.tmp / "sessions"):
            data = codex_usage.fetch_log_usage()
        self.assertEqual(data["source"], "log")
        self.assertEqual([(w["key"], w["pct"]) for w in codex_usage.get_windows(data)],
                         [("primary", 30.0), ("secondary", 90.0)])

    def test_passed_reset_counts_as_unused(self):
        data = {"rate_limits": {"primary": {"used_percent": 80, "resets_at": 1}}, "timestamp": None}
        (w,) = codex_usage.get_windows(data)
        self.assertEqual((w["pct"], w["resets_at"]), (0.0, None))

    def test_old_resets_in_seconds_format(self):
        now = datetime.now(timezone.utc)
        data = {"rate_limits": {"primary": {"used_percent": 10, "resets_in_seconds": 600}}, "timestamp": now}
        (w,) = codex_usage.get_windows(data)
        self.assertAlmostEqual(datetime.fromisoformat(w["resets_at"]).timestamp(), now.timestamp() + 600, delta=1)


class CodexAppServerParseTest(unittest.TestCase):
    def test_parses_rate_limits_and_account(self):
        responses = [
            {"id": 1, "result": {"rateLimits": {
                "primary": {"usedPercent": 42, "windowDurationMins": 300, "resetsAt": FUTURE},
                "secondary": {"usedPercent": 7, "resetsAt": FUTURE}}}},
            {"id": 2, "result": {"account": {"type": "chatgpt", "email": "x@example.com", "planType": "pro"}}},
        ]
        with mock.patch.object(codex_usage, "app_server_call", return_value=responses):
            data = codex_usage.fetch_usage()
        self.assertEqual(data["source"], "app-server")
        self.assertEqual(data["account"], {"email": "x@example.com", "plan": "Pro"})
        self.assertEqual([w["pct"] for w in codex_usage.get_windows(data)], [42.0, 7.0])

    def test_auth_error_becomes_login_message(self):
        responses = [{"id": 1, "error": {"code": -32603, "message": "GET ... failed: 401 Unauthorized"}},
                     {"id": 2, "result": {"account": None}}]
        with mock.patch.object(codex_usage, "app_server_call", return_value=responses):
            with self.assertRaisesRegex(codex_usage.CodexUsageError, "codex login"):
                codex_usage.fetch_app_server()

    def test_falls_back_to_logs_and_reports_both_failures(self):
        boom = codex_usage.CodexUsageError("Codex CLI not found")
        with mock.patch.object(codex_usage, "app_server_call", side_effect=boom), \
                mock.patch.object(codex_usage, "SESSIONS_DIR", Path("/nonexistent/sessions")):
            with self.assertRaisesRegex(codex_usage.CodexUsageError, "Codex CLI not found / Codex sessions not found"):
                codex_usage.fetch_usage()


FAKE_APP_SERVER = textwrap.dedent('''
    import json, sys
    for line in sys.stdin:
        msg = json.loads(line)
        if "id" not in msg:
            continue  # notifications such as "initialized"
        sys.stdout.write(json.dumps({"method": "configWarning", "params": {}}) + "\\n")  # noise to ignore
        if msg["method"] == "initialize":
            result = {"userAgent": "fake"}
        elif msg["method"] == "account/rateLimits/read":
            result = {"rateLimits": {"primary": {"usedPercent": 55, "resetsAt": %d}}}
        else:
            result = {"account": {"type": "chatgpt", "email": "fake@example.com", "planType": "plus"}}
        sys.stdout.write(json.dumps({"id": msg["id"], "result": result}) + "\\n")
        sys.stdout.flush()
''' % FUTURE)


class CodexAppServerProcessTest(TempDirTest):
    """Drives app_server_call against a fake `codex` executable (POSIX script or Windows .cmd)."""

    def setUp(self):
        super().setUp()
        (self.tmp / "fake_codex.py").write_text(FAKE_APP_SERVER, encoding="utf-8")
        if os.name == "nt":
            (self.tmp / "codex.cmd").write_text(
                f'@"{sys.executable}" "{self.tmp / "fake_codex.py"}" %*\r\n', encoding="utf-8")
        else:
            exe = self.tmp / "codex"
            exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{self.tmp / "fake_codex.py"}" "$@"\n')
            exe.chmod(0o755)

    def test_round_trip(self):
        with mock.patch.dict(os.environ, {"PATH": str(self.tmp)}), \
                mock.patch.object(codex_usage, "EXTRA_BIN_DIRS", []):
            data = codex_usage.fetch_app_server()
        self.assertEqual(data["rate_limits"]["primary"]["used_percent"], 55)
        self.assertEqual(data["account"], {"email": "fake@example.com", "plan": "Plus"})

    def test_missing_cli(self):
        with mock.patch.dict(os.environ, {"PATH": str(self.tmp / "empty")}), \
                mock.patch.object(codex_usage, "EXTRA_BIN_DIRS", []):
            with self.assertRaisesRegex(codex_usage.CodexUsageError, "not found"):
                codex_usage.fetch_app_server()


# ---------------------------------------------------------------- snapshot: cache, alerts, services

def window(key="five_hour", pct=10.0, resets_at=None):
    return {"key": key, "label": key, "pct": pct, "resets_at": resets_at}


class CacheTest(unittest.TestCase):
    def test_fresh_values_are_stored(self):
        state = {}
        windows, stale = us._with_cache(state, "Claude", [window()], None)
        self.assertIsNone(stale)
        self.assertIn("Claude", state["cache"])

    def test_error_uses_recent_cache(self):
        state = {}
        us._with_cache(state, "Claude", [window(pct=30)], None)
        windows, stale = us._with_cache(state, "Claude", [], "Claude: offline")
        self.assertIsNotNone(stale)
        self.assertEqual(windows[0]["pct"], 30)

    def test_error_ignores_old_cache(self):
        old = (datetime.now(timezone.utc) - us.CACHE_MAX_AGE - timedelta(minutes=1)).isoformat()
        state = {"cache": {"Claude": {"windows": [window()], "fetched_at": old}}}
        self.assertEqual(us._with_cache(state, "Claude", [], "err"), ([], None))

    def test_cached_window_past_reset_counts_as_unused(self):
        state = {}
        us._with_cache(state, "Claude", [window(pct=90, resets_at="2000-01-01T00:00:00+00:00")], None)
        windows, _ = us._with_cache(state, "Claude", [], "err")
        self.assertEqual((windows[0]["pct"], windows[0]["resets_at"]), (0.0, None))


class NotificationTest(unittest.TestCase):
    def alerts(self, state, remaining):
        return us._check_notifications(state, "Codex", [window("primary", 100 - remaining)])

    def test_thresholds_fire_once_and_rearm(self):
        state = {}
        self.assertEqual(self.alerts(state, 50), [])
        self.assertEqual(len(self.alerts(state, 15)), 1)   # crossed 20
        self.assertEqual(self.alerts(state, 14), [])       # no repeat
        self.assertEqual(len(self.alerts(state, 3)), 1)    # crossed 5
        self.assertEqual(self.alerts(state, 90), [])       # recovered: re-armed
        self.assertEqual(len(self.alerts(state, 15)), 1)

    def test_jumping_past_both_thresholds_alerts_once(self):
        self.assertEqual(len(self.alerts({}, 2)), 1)


class EnabledServicesTest(TempDirTest):
    def patch_detect(self, claude: bool, codex: bool):
        return mock.patch.object(us, "_detected", side_effect=lambda n: {"Claude": claude, "Codex": codex}[n])

    def test_auto_detect(self):
        with mock.patch.object(us, "CONFIG_FILE", self.tmp / "none.json"):
            with self.patch_detect(False, True):
                self.assertEqual(us.enabled_services(), ["Codex"])
            with self.patch_detect(False, False):
                self.assertEqual(us.enabled_services(), ["Claude"])  # dashed "please log in" ring

    def test_config_pins_services(self):
        cfg = self.tmp / "config.json"
        with mock.patch.object(us, "CONFIG_FILE", cfg), self.patch_detect(True, True):
            cfg.write_text('{"services": ["Codex"]}', encoding="utf-8")
            self.assertEqual(us.enabled_services(), ["Codex"])
            for broken in ('{"services": []}', "[1, 2]", "{oops"):
                cfg.write_text(broken, encoding="utf-8")
                self.assertEqual(us.enabled_services(), ["Claude", "Codex"], broken)


class PollingTest(unittest.TestCase):
    def fake_fetch(self, results):
        calls = []

        def fetch(name):
            calls.append(name)
            return results.pop(0)
        return calls, fetch

    def test_codex_reuses_recent_values_between_fetches(self):
        state = {}
        ok = ([window("primary", 30)], None, "note", {"email": "a@example.com", "plan": None}, None)
        calls, fetch = self.fake_fetch([ok, ok])
        with mock.patch.object(us, "_fetch", side_effect=fetch):
            us._service_data(state, "Codex")
            windows, error, stale, note, account = us._service_data(state, "Codex")
            self.assertEqual(len(calls), 1)  # second call served from cache
            self.assertEqual((windows[0]["pct"], error, stale, note, account["email"]),
                             (30, None, None, "note", "a@example.com"))
            old = datetime.now(timezone.utc) - timedelta(seconds=us.FETCH_INTERVAL["Codex"] + 1)
            state["cache"]["Codex"]["fetched_at"] = old.isoformat()
            us._service_data(state, "Codex")
            self.assertEqual(len(calls), 2)

    def test_claude_fetches_every_time(self):
        state = {}
        ok = ([window()], None, None, None, None)
        calls, fetch = self.fake_fetch([ok, ok])
        with mock.patch.object(us, "_fetch", side_effect=fetch):
            us._service_data(state, "Claude")
            us._service_data(state, "Claude")
        self.assertEqual(len(calls), 2)

    def test_rate_limit_backs_off_with_cached_values(self):
        state = {}
        ok = ([window(pct=40)], None, None, None, None)
        limited = ([], "Claude: Rate limited (HTTP 429)", None, None, 120.0)
        calls, fetch = self.fake_fetch([ok, limited, ok])
        with mock.patch.object(us, "_fetch", side_effect=fetch):
            us._service_data(state, "Claude")
            us._service_data(state, "Claude")                      # gets 429
            windows, error, stale, _, _ = us._service_data(state, "Claude")  # backing off
            self.assertEqual(len(calls), 2)
            self.assertEqual(windows[0]["pct"], 40)
            self.assertIsNotNone(stale)
            self.assertIn("再開", error)
            state["backoff"]["Claude"]["until"] = "2000-01-01T00:00:00+00:00"  # backoff over
            windows, error, stale, _, _ = us._service_data(state, "Claude")
            self.assertEqual((len(calls), error, stale), (3, None, None))
            self.assertNotIn("Claude", state["backoff"])

    def test_claude_429_reads_retry_after(self):
        import urllib.error
        err = urllib.error.HTTPError("https://x", 429, "Too Many Requests", {"Retry-After": "42"}, None)
        with mock.patch.object(claude_usage.urllib.request, "urlopen", side_effect=err):
            with self.assertRaises(claude_usage.UsageError) as cm:
                claude_usage.fetch_usage(token="t")
        self.assertEqual(cm.exception.retry_after, 42.0)


# ---------------------------------------------------------------- icons

class IconTest(unittest.TestCase):
    def test_menu_bar_png_size_scales_with_gauges(self):
        for n, width in ((1, 36), (2, 82)):
            png = us.render_icon([(50, 50, us.CLAUDE_RGB, False)] * n)
            self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II", png[16:24]), (width, 36))

    def test_tray_ico_entries(self):
        sizes = [16, 20, 24, 32]
        ico = us.render_ico(None, 0, us.CODEX_RGB, True, sizes)  # dashed + depleted + stale paths
        reserved, kind, count = struct.unpack("<HHH", ico[:6])
        self.assertEqual((reserved, kind, count), (0, 1, len(sizes)))
        for i, size in enumerate(sizes):
            w, h, _, _, planes, bpp, length, offset = struct.unpack("<BBBBHHII", ico[6 + 16 * i:22 + 16 * i])
            self.assertEqual((w, h, planes, bpp), (size, size, 1, 32))
            hdr = struct.unpack("<IiiHH", ico[offset:offset + 16])
            self.assertEqual(hdr, (40, size, size * 2, 1, 32))
            self.assertEqual(length, 40 + size * size * 4 + ((size + 31) // 32) * 4 * size)

    def test_tray_pixels_corners_are_transparent(self):
        px = us.render_tray_pixels(60, 60, us.CLAUDE_RGB, False, 16)
        self.assertEqual(px[3], 0)                 # top-left alpha
        self.assertEqual(px[(8 * 16 + 15) * 4 + 3], 255)  # right edge of the ring is solid


# ---------------------------------------------------------------- Windows tray JSON

class UsageJsonTest(unittest.TestCase):
    def test_output_is_ascii_json_with_icons(self):
        snap = {"services": [{
            "name": "Claude", "rgb": us.CLAUDE_RGB, "account": "a@example.com · Pro",
            "windows": [window(pct=20, resets_at=None)], "error": None, "stale_since": None,
            "note": None, "outer": 80.0, "inner": None}], "alerts": [("タイトル", "本文")]}
        buf = io.StringIO()
        with mock.patch.object(usage_json.us, "collect", return_value=snap), \
                mock.patch.object(sys, "argv", ["usage_json.py", "--size", "20"]), redirect_stdout(buf):
            usage_json.main()
        raw = buf.getvalue()
        raw.encode("ascii")  # PowerShell reads it as UTF-8, but ASCII keeps it codepage-proof
        out = json.loads(raw)
        ico = base64.b64decode(out["services"][0]["icon"])
        self.assertEqual(struct.unpack("<HHH", ico[:6])[2], 4)  # 16/20/24/32 (20 already included)
        self.assertEqual(out["alerts"], [{"title": "タイトル", "body": "本文"}])


if __name__ == "__main__":
    unittest.main()
