#!/usr/bin/env python3
"""Claude clock + usage widget — always-on-top concentric watch face.

One compact circle: analog clock in the center, wrapped by two progress
rings — outer = Session (5h), inner = Weekly. Space-efficient and readable.

Usage:  python3 ~/claude_clock_widget/clock_widget.py
Requires: sudo apt install python3-tk  (and WSLg for GUI display on WSL2)
"""

import math
import sys
import threading
from datetime import datetime

try:
    import tkinter as tk
    from tkinter import font as tkfont
except ImportError:
    sys.exit("tkinter is not installed. Run: sudo apt install python3-tk")

from claude_usage import UsageError, fetch_usage, fmt_reset, get_windows

REFRESH_MS = 60_000
CLOCK_MS = 1_000

PAD = 14
DIAM = 184             # outer diameter of the whole dial
RING_W = 13            # progress ring thickness
RING_GAP = 4           # gap between the two rings
LEGEND_H = 40          # space under the dial for the two legend lines

BG = "#16161a"
TRACK = "#2c2c33"
FACE = "#1f1f26"
FG_TEXT = "#ececf0"
FG_SUB = "#7c7c86"
FG_ERR = "#ff7070"
HAND_HOUR = "#ececf0"
HAND_MIN = "#9bd1ff"
HAND_SEC = "#ff6b6b"


def color(pct: float) -> str:
    if pct >= 80:
        return "#ff5555"
    if pct >= 50:
        return "#f1c40f"
    return "#2ecc71"


class ClockWidget:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Claude Clock")
        root.configure(bg=BG)
        root.attributes("-topmost", True)
        root.resizable(False, False)

        self.width = DIAM + 2 * PAD
        self.height = DIAM + LEGEND_H + 2 * PAD

        self.canvas = tk.Canvas(root, bg=BG, width=self.width, height=self.height,
                                highlightthickness=0)
        self.canvas.pack(padx=8, pady=8)

        # dial geometry (center of the circle)
        self.cx = self.width / 2
        self.cy = PAD + DIAM / 2
        R = DIAM / 2
        self.r_session = R - RING_W / 2                      # outer ring centerline
        self.r_weekly = self.r_session - RING_W - RING_GAP   # inner ring centerline
        self.r_face = self.r_weekly - RING_W / 2 - 5         # clock face radius

        self.pct_font = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        self.legend_font = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        self.sub_font = tkfont.Font(family="Segoe UI", size=8)

        self.windows: dict[str, dict] = {}
        self.error: str | None = None

        self.draw()          # rings + clock face + legend
        self.tick()          # animate hands every second
        self.schedule_fetch()
        self.keep_on_top()

    def keep_on_top(self):
        # WSLg may drop the topmost hint; re-assert it periodically
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.root.after(2000, self.keep_on_top)

    # --- data ---

    def schedule_fetch(self):
        threading.Thread(target=self.fetch, daemon=True).start()
        self.root.after(REFRESH_MS, self.schedule_fetch)

    def fetch(self):
        try:
            data = fetch_usage()
            windows = {w["key"]: w for w in get_windows(data)}
            err = None
        except UsageError as e:
            windows, err = self.windows, str(e)
        self.root.after(0, lambda: self.update_data(windows, err))

    def update_data(self, windows: dict[str, dict], error: str | None):
        self.windows = windows
        self.error = error
        self.draw()

    # --- drawing ---

    def draw(self):
        c = self.canvas
        c.delete("all")
        self.draw_ring(self.r_session, self.windows.get("five_hour"))
        self.draw_ring(self.r_weekly, self.windows.get("seven_day"))
        self.draw_clock_face()
        self.draw_hands()
        self.draw_legend()

    def draw_ring(self, rc: float, w: dict | None):
        c = self.canvas
        x0, y0, x1, y1 = self.cx - rc, self.cy - rc, self.cx + rc, self.cy + rc
        c.create_oval(x0, y0, x1, y1, outline=TRACK, width=RING_W)
        if w and w["pct"] > 0:
            c.create_arc(x0, y0, x1, y1, start=90, extent=-3.6 * min(w["pct"], 100),
                         style=tk.ARC, outline=color(w["pct"]), width=RING_W)

    def draw_clock_face(self):
        c = self.canvas
        cx, cy, r = self.cx, self.cy, self.r_face
        c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=FACE, outline="")
        for h in range(12):
            ang = math.radians(h * 30)
            sin, cos = math.sin(ang), math.cos(ang)
            cardinal = h % 3 == 0
            inner = r * (0.74 if cardinal else 0.82)
            outer = r * 0.93
            c.create_line(cx + inner * sin, cy - inner * cos,
                          cx + outer * sin, cy - outer * cos,
                          fill=FG_TEXT if cardinal else FG_SUB,
                          width=3 if cardinal else 1)

    def _hand(self, length_frac: float, ang_deg: float):
        ang = math.radians(ang_deg)
        L = self.r_face * length_frac
        return (self.cx, self.cy,
                self.cx + L * math.sin(ang), self.cy - L * math.cos(ang))

    def draw_hands(self):
        c = self.canvas
        c.delete("hands")
        now = datetime.now()
        h, m, s = now.hour % 12, now.minute, now.second
        c.create_line(*self._hand(0.52, (h + m / 60) * 30), fill=HAND_HOUR, width=4,
                      capstyle=tk.ROUND, tags="hands")
        c.create_line(*self._hand(0.76, (m + s / 60) * 6), fill=HAND_MIN, width=3,
                      capstyle=tk.ROUND, tags="hands")
        c.create_line(*self._hand(0.86, s * 6), fill=HAND_SEC, width=1,
                      capstyle=tk.ROUND, tags="hands")
        c.create_oval(self.cx - 4, self.cy - 4, self.cx + 4, self.cy + 4,
                      fill=HAND_HOUR, outline="", tags="hands")

    def draw_legend(self):
        """Two compact lines under the dial: Session / Weekly with % and reset."""
        c = self.canvas
        if self.error and not self.windows:
            c.create_text(self.width / 2, self.cy + self.r_face / 2,
                          text=self.error, fill=FG_ERR, font=self.sub_font,
                          width=self.width - 30)
            return

        rows = [
            ("Session", HAND_SEC, self.windows.get("five_hour")),
            ("Weekly", HAND_MIN, self.windows.get("seven_day")),
        ]
        y = self.cy + DIAM / 2 + 6
        for label, dot, w in rows:
            cx = self.width / 2
            c.create_oval(cx - 70, y - 4, cx - 62, y + 4, fill=dot, outline="")
            c.create_text(cx - 56, y, text=label, fill=FG_TEXT, font=self.legend_font,
                          anchor="w")
            if w is None:
                c.create_text(cx + 70, y, text="—", fill=FG_SUB, font=self.legend_font,
                              anchor="e")
            else:
                pct = w["pct"]
                c.create_text(cx + 8, y, text=f"{pct:.0f}%", fill=color(pct),
                              font=self.legend_font, anchor="w")
                reset = fmt_reset(w["resets_at"])
                if reset:
                    c.create_text(cx + 70, y, text=reset, fill=FG_SUB,
                                  font=self.sub_font, anchor="e")
            y += 18

    def tick(self):
        self.draw_hands()
        self.root.after(CLOCK_MS, self.tick)


def main():
    try:
        root = tk.Tk()
    except tk.TclError as e:
        sys.exit(f"Could not open a display: {e}\n"
                 "On WSL2 this requires WSLg (Windows 11, or updated WSL on Windows 10).")
    ClockWidget(root)
    root.mainloop()


if __name__ == "__main__":
    main()
