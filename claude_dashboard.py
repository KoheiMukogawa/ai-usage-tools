#!/usr/bin/env python3
"""Claude usage browser dashboard — SVG donut gauges, auto-refreshing.

Usage:  python3 ~/claude_dashboard.py [port]
Then open http://localhost:8765 in your browser.
"""

import json
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

from claude_usage import UsageError, fetch_usage, fmt_reset, get_windows

DEFAULT_PORT = 8765
CACHE_TTL = 55  # seconds — avoid hammering the endpoint

_cache = {"data": None, "error": None, "fetched_at": 0.0}
_lock = threading.Lock()


def get_usage_cached() -> dict:
    with _lock:
        now = time.time()
        if now - _cache["fetched_at"] < CACHE_TTL and (_cache["data"] or _cache["error"]):
            pass
        else:
            try:
                _cache["data"] = fetch_usage()
                _cache["error"] = None
            except UsageError as e:
                _cache["error"] = str(e)
            _cache["fetched_at"] = now

        if _cache["error"]:
            return {"error": _cache["error"]}
        windows = get_windows(_cache["data"])
        for w in windows:
            w["reset_text"] = fmt_reset(w["resets_at"])
        return {"windows": windows, "fetched_at": _cache["fetched_at"]}


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Claude Usage</title>
<style>
  body {
    margin: 0; padding: 24px;
    background: #1a1a1e; color: #e8e8ea;
    font-family: "Segoe UI", system-ui, sans-serif;
    display: flex; flex-direction: column; align-items: center;
  }
  h1 { font-size: 16px; font-weight: 600; color: #b8b8c0; margin: 0 0 20px; }
  #gauges { display: flex; gap: 32px; flex-wrap: wrap; justify-content: center; }
  .gauge { display: flex; flex-direction: column; align-items: center; }
  .gauge svg { transform: rotate(-90deg); }
  .gauge .pct {
    font-size: 26px; font-weight: 700;
    transform: rotate(90deg); transform-origin: center;
  }
  .gauge .label { margin-top: 10px; font-size: 14px; color: #c8c8d0; }
  .gauge .reset { margin-top: 2px; font-size: 12px; color: #808088; }
  #status { margin-top: 24px; font-size: 11px; color: #606068; }
  #error { margin-top: 24px; color: #ff7070; font-size: 14px; white-space: pre-wrap; }
</style>
</head>
<body>
<h1>Claude Usage</h1>
<div id="gauges"></div>
<div id="error"></div>
<div id="status"></div>
<script>
const R = 54, C = 2 * Math.PI * R;

function color(pct) {
  if (pct >= 80) return "#ff5555";
  if (pct >= 50) return "#f1c40f";
  return "#2ecc71";
}

function gauge(w) {
  const offset = C * (1 - w.pct / 100);
  return `
  <div class="gauge">
    <svg width="140" height="140" viewBox="0 0 140 140">
      <circle cx="70" cy="70" r="${R}" fill="none" stroke="#2e2e34" stroke-width="14"/>
      <circle cx="70" cy="70" r="${R}" fill="none" stroke="${color(w.pct)}" stroke-width="14"
              stroke-linecap="round" stroke-dasharray="${C}" stroke-dashoffset="${offset}"
              style="transition: stroke-dashoffset 0.8s ease, stroke 0.8s ease"/>
      <text x="70" y="70" text-anchor="middle" dominant-baseline="central"
            class="pct" fill="${color(w.pct)}"
            transform="rotate(90 70 70)">${Math.round(w.pct)}%</text>
    </svg>
    <div class="label">${w.label}</div>
    <div class="reset">${w.reset_text ? "resets " + w.reset_text : ""}</div>
  </div>`;
}

async function refresh() {
  const errEl = document.getElementById("error");
  const statusEl = document.getElementById("status");
  try {
    const resp = await fetch("/api/usage");
    const data = await resp.json();
    if (data.error) {
      errEl.textContent = data.error;
      return;
    }
    errEl.textContent = "";
    document.getElementById("gauges").innerHTML = data.windows.map(gauge).join("");
    statusEl.textContent = "updated " + new Date().toLocaleTimeString() + " · refreshes every 60s";
  } catch (e) {
    errEl.textContent = "Failed to reach local server: " + e;
  }
}

refresh();
setInterval(refresh, 60000);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/usage":
            body = json.dumps(get_usage_cached()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass  # silence per-request logging


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"Claude usage dashboard running at http://localhost:{port}")
    print("Open it in your browser. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
