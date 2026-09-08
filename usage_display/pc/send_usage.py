#!/usr/bin/env python3
"""Claude使用量をPicoのTFTディスプレイへ送るPC側スクリプト.

仕組み:
  - 既存の claude_usage.py (ウィジェットと同じもの) で使用量を取得
  - 60秒ごとに Pico (ILI9341表示機) へ HTTP POST で送信

使い方:
  1. 下の PICO_IP を、Picoが起動時に表示したIPアドレスに書き換える
  2. claude_usage.py がこのスクリプトから import できる場所に置く
     (例: 同じフォルダ、または ~/ に置いて PYTHONPATH を通す)
  3. 実行:  python3 send_usage.py
     → 60秒ごとに "sent ..." と表示されれば成功。PicoのTFTが更新される。

  常時動かしたい場合は、PC起動時に自動実行する設定(タスクスケジューラ/cron等)を後で追加する。
"""

import json
import time
import urllib.request

# 既存ウィジェットと同じモジュールを利用
from claude_usage import fetch_usage, get_windows, fmt_reset  # noqa: E402

# ===== ここを書き換える =====
PICO_IP = "192.168.x.x"     # Picoが起動時に表示したIPアドレス
INTERVAL = 60               # 送信間隔(秒)
# ===========================


def build_payload():
    """ウィジェットと同じデータを、Picoが扱いやすい形に整える."""
    data = fetch_usage()
    out = []
    for w in get_windows(data):
        out.append({
            "label": w["label"],
            "pct": round(w["pct"]),
            "reset": fmt_reset(w["resets_at"]) or "",
        })
    return {"windows": out}


def send(payload):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "http://%s/update" % PICO_IP,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.read().decode("utf-8", "ignore")


def main():
    print("Picoへ送信開始 (Ctrl+C で停止)  ->", PICO_IP)
    while True:
        try:
            payload = build_payload()
            result = send(payload)
            print("sent:", payload, "->", result)
        except Exception as e:
            print("error:", e)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
