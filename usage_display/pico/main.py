# main.py  --- Pico WH : Claude使用量を2.8インチTFT(ILI9341)に表示する受信機
#
# 役割:
#   1. WiFiに接続し、NTPで時刻を合わせる(時計表示用)
#   2. ILI9341 (2.8インチ SPI TFT / MSP2807) を初期化
#   3. ポート80でHTTPサーバーを立て、PCから送られてくる使用量(JSON)を受信
#   4. 受信したデータを「ラベル + % + カラーバー + リセット時刻」で描画、上部に時計
#
# 事前にPicoへ入れておくファイル(Thonnyで保存):
#   - ili9341.py       … 表示ドライバ
#   - xglcd_font.py    … 大きい文字用フォントの読み込み
#   - Unispace12x24.c  … フォントデータ(12x24)
#   いずれも rdagger/micropython-ili9341 (GitHub) から入手。READMEに手順あり。
#
# ※ このコードは rdagger 版ドライバのAPIを前提にしています。
#   実機接続時に少しだけ調整が要る場合があります(その時は一緒に直します)。

import network
import socket
import time
import json
from machine import Pin, SPI

# ===== WiFi設定(反映済み) =====
SSID = ""
PASSWORD = ""            # 自分の自宅WiFiのパスワードを入れる（リポジトリには入れない）
JST_OFFSET = 9 * 3600          # 日本標準時 = UTC+9
# ===============================

# --- 表示ドライバ ---
from ili9341 import Display, color565
from xglcd_font import XglcdFont

# ===== 配線(SPI0)。READMEの配線表と一致させること =====
#   SCK  -> GP18 (物理24)
#   MOSI -> GP19 (物理25)
#   CS   -> GP17 (物理22)
#   DC   -> GP15 (物理20)
#   RST  -> GP14 (物理19)
spi = SPI(0, baudrate=40_000_000, sck=Pin(18), mosi=Pin(19))
display = Display(spi, dc=Pin(15), cs=Pin(17), rst=Pin(14),
                  width=240, height=320, rotation=90)   # rotation=90 -> 横向き 320x240

WIDTH = 320
HEIGHT = 240

# --- 色 ---
BG     = color565(0, 0, 0)
WHITE  = color565(232, 232, 234)
GRAY   = color565(128, 128, 136)
TRACK  = color565(46, 46, 52)
ACCENT = color565(217, 119, 87)     # 時計のオレンジ
GREEN  = color565(46, 204, 113)
YELLOW = color565(241, 196, 15)
RED    = color565(255, 85, 85)

# 大きい文字用フォント(12x24)。ラベル等は内蔵の8x8を使う。
big = XglcdFont('Unispace12x24.c', 12, 24)

led = Pin("LED", Pin.OUT)

# 受信した使用量データ。例: [{"label":"Opus","pct":45,"reset":"15:00"}, ...]
windows = []
last_minute = -1


def color_for(pct):
    if pct >= 80:
        return RED
    if pct >= 50:
        return YELLOW
    return GREEN


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(SSID, PASSWORD)
        for _ in range(20):
            if wlan.isconnected():
                break
            led.toggle()
            time.sleep(1)
    if wlan.isconnected():
        led.on()
        ip = wlan.ifconfig()[0]
        print("WiFi接続成功! PicoのIP:", ip)
        return ip
    led.off()
    raise RuntimeError("WiFi接続失敗。SSID/パスワードを確認。")


def sync_time():
    try:
        import ntptime
        ntptime.settime()          # RTCをUTCに合わせる
        print("時刻同期OK")
        return True
    except Exception as e:
        print("時刻同期スキップ:", e)
        return False


def now_jst():
    return time.localtime(time.time() + JST_OFFSET)


# ---------- 描画 ----------
# 表示まわりは全部この区画にまとめてある。実機で微調整するならここを触る。

def draw_clock(force=False):
    """上部の日付と時計。分が変わった時だけ描く(チラつき防止)。"""
    global last_minute
    t = now_jst()
    if not force and t[4] == last_minute:
        return
    last_minute = t[4]
    # 上部40pxをクリア
    display.fill_rectangle(0, 0, WIDTH, 40, BG)
    date_str = "%04d-%02d-%02d" % (t[0], t[1], t[2])
    time_str = "%02d:%02d" % (t[3], t[4])
    display.draw_text8x8(8, 14, date_str, GRAY, background=BG)
    # 時計(大): 右寄せ。12px/文字 × 5文字 = 60px
    display.draw_text(WIDTH - 64, 8, time_str, big, ACCENT, background=BG)
    display.draw_hline(0, 42, WIDTH, TRACK)


def draw_windows():
    """使用量ゲージ群。データ受信時に呼ぶ。"""
    top = 48
    area_h = HEIGHT - top
    display.fill_rectangle(0, top, WIDTH, area_h, BG)

    if not windows:
        display.draw_text8x8(8, top + 20, "Waiting for PC data...", GRAY, background=BG)
        return

    n = len(windows)
    row_h = area_h // n
    bar_x = 8
    bar_w = WIDTH - 16
    for i, w in enumerate(windows):
        y = top + i * row_h
        label = str(w.get("label", "?"))
        pct = int(w.get("pct", 0))
        reset = str(w.get("reset", ""))
        col = color_for(pct)

        # ラベル(左) と % (大・右)
        display.draw_text8x8(bar_x, y + 6, label, WHITE, background=BG)
        pct_str = "%d%%" % pct
        display.draw_text(WIDTH - 8 - len(pct_str) * 12, y + 2, pct_str, big, col, background=BG)

        # バー
        by = y + 30
        bh = 16
        display.fill_rectangle(bar_x, by, bar_w, bh, TRACK)
        fill = int(bar_w * min(max(pct, 0), 100) / 100)
        if fill > 0:
            display.fill_rectangle(bar_x, by, fill, bh, col)

        # リセット時刻
        if reset:
            display.draw_text8x8(bar_x, by + bh + 6, "resets " + reset, GRAY, background=BG)


# ---------- 通信 ----------

def recv_request(cl):
    cl.settimeout(2)
    data = b""
    try:
        while True:
            chunk = cl.recv(512)
            if not chunk:
                break
            data += chunk
            if b"\r\n\r\n" in data:
                head, _, body = data.partition(b"\r\n\r\n")
                clen = 0
                for line in head.split(b"\r\n"):
                    if line.lower().startswith(b"content-length:"):
                        try:
                            clen = int(line.split(b":")[1])
                        except Exception:
                            clen = 0
                if len(body) >= clen:
                    break
    except OSError:
        pass
    return data


def handle(cl):
    global windows
    raw = recv_request(cl)
    text = raw.decode("utf-8", "ignore") if raw else ""
    if text.startswith("POST /update"):
        body = text.split("\r\n\r\n", 1)[1] if "\r\n\r\n" in text else ""
        try:
            payload = json.loads(body)
            windows = payload.get("windows", [])
            cl.send(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nOK")
            draw_windows()
            print("受信:", windows)
        except Exception as e:
            cl.send(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n")
            print("JSON解析エラー:", e)
    else:
        # 動作確認用の簡単な応答
        cl.send(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nPico usage display OK")
    cl.close()


def serve():
    addr = socket.getaddrinfo("0.0.0.0", 80)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(1)
    s.settimeout(1)             # 1秒待っても接続がなければ時計だけ更新
    print("受信待機中 ...")
    while True:
        try:
            cl, _ = s.accept()
            handle(cl)
        except OSError:
            # accept のタイムアウト -> 時計を更新
            draw_clock()


# ===== 起動 =====
display.clear(BG)
display.draw_text8x8(8, 8, "Connecting WiFi...", GRAY, background=BG)
ip = connect_wifi()
sync_time()
display.clear(BG)
draw_clock(force=True)
draw_windows()             # まだデータが無いので "Waiting..." 表示
print("ブラウザ確認用: http://" + ip + "  / PCの送信先IPもこれ")
serve()
