#!/usr/bin/env python3
"""Claude usage desktop widget — always-on-top window with circular gauges (tkinter/WSLg).

Usage:  python3 ~/claude_widget.py
Requires: sudo apt install python3-tk  (and WSLg for GUI display on WSL2)
"""

import sys
import threading

try:
    import tkinter as tk
    from tkinter import font as tkfont
except ImportError:
    sys.exit("tkinter is not installed. Run: sudo apt install python3-tk")

from datetime import datetime

from claude_usage import UsageError, fetch_usage, fmt_reset, get_windows

REFRESH_MS = 60_000
CLOCK_MS = 1_000
GAUGE_SIZE = 110
GAUGE_PAD = 14
ARC_WIDTH = 11
CLOCK_H = 42

BG = "#1a1a1e"
TRACK = "#2e2e34"
FG_TEXT = "#e8e8ea"
FG_SUB = "#808088"
FG_ERR = "#ff7070"
FG_CLOCK = "#d97757"


def color(pct: float) -> str:
    if pct >= 80:
        return "#ff5555"
    if pct >= 50:
        return "#f1c40f"
    return "#2ecc71"


class UsageWidget:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Claude Usage")
        root.configure(bg=BG)
        root.attributes("-topmost", True)
        root.resizable(False, False)

        self.canvas = tk.Canvas(root, bg=BG, highlightthickness=0)
        self.canvas.pack(padx=8, pady=8)

        self.pct_font = tkfont.Font(family="Segoe UI", size=14, weight="bold")
        self.label_font = tkfont.Font(family="Segoe UI", size=9)
        self.sub_font = tkfont.Font(family="Segoe UI", size=8)
        self.clock_font = tkfont.Font(family="Segoe UI", size=17, weight="bold")
        self.date_font = tkfont.Font(family="Segoe UI", size=8)

        self.windows: list[dict] = []
        self.error: str | None = None
        self.clock_id: int | None = None

        self.draw()          # initial placeholder
        self.tick()          # clock + countdown, every second
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
            windows = get_windows(data)
            err = None
        except UsageError as e:
            windows, err = self.windows, str(e)
        self.root.after(0, lambda: self.update_data(windows, err))

    def update_data(self, windows: list[dict], error: str | None):
        self.windows = windows
        self.error = error
        self.draw()

    # --- drawing ---

    def draw(self):
        c = self.canvas
        c.delete("all")
        self.clock_id = None

        n = max(1, len(self.windows))
        cell = GAUGE_SIZE + GAUGE_PAD
        width = n * cell
        height = CLOCK_H + GAUGE_SIZE + 44
        c.configure(width=width, height=height)

        # --- clock (top): date line + big time line, updated by tick() ---
        c.create_text(width / 2, 11, text=self._date_str(), fill=FG_SUB, font=self.date_font)
        self.clock_id = c.create_text(width / 2, 28, text=self._time_str(),
                                      fill=FG_CLOCK, font=self.clock_font)

        if not self.windows:
            msg = self.error or "Loading..."
            c.create_text(width / 2, CLOCK_H + (height - CLOCK_H) / 2, text=msg,
                          fill=FG_SUB, font=self.label_font, width=width - 20)
            return

        for i, w in enumerate(self.windows):
            x0 = i * cell + GAUGE_PAD / 2 + ARC_WIDTH / 2
            y0 = CLOCK_H + ARC_WIDTH / 2 + 4
            x1 = x0 + GAUGE_SIZE - ARC_WIDTH
            y1 = y0 + GAUGE_SIZE - ARC_WIDTH
            cx = (x0 + x1) / 2
            cy = (y0 + y1) / 2
            pct = w["pct"]

            # track ring + progress arc (starts at top, clockwise)
            c.create_oval(x0, y0, x1, y1, outline=TRACK, width=ARC_WIDTH)
            if pct > 0:
                c.create_arc(x0, y0, x1, y1, start=90, extent=-3.6 * min(pct, 100),
                             style=tk.ARC, outline=color(pct), width=ARC_WIDTH)

            c.create_text(cx, cy, text=f"{pct:.0f}%", fill=color(pct), font=self.pct_font)
            c.create_text(cx, y1 + 14, text=w["label"], fill=FG_TEXT, font=self.label_font)
            reset = fmt_reset(w["resets_at"])
            if reset:
                c.create_text(cx, y1 + 28, text=f"resets {reset}", fill=FG_SUB, font=self.sub_font)

        if self.error:
            c.create_text(width / 2, height - 4, text="(refresh failed — showing last data)",
                          fill=FG_ERR, font=self.sub_font)

    # --- clock ---

    def _time_str(self) -> str:
        return datetime.now().strftime("%H:%M")

    def _date_str(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def tick(self):
        if self.clock_id is not None:
            self.canvas.itemconfigure(self.clock_id, text=self._time_str())
        self.root.after(CLOCK_MS, self.tick)


def main():
    try:
        root = tk.Tk()
    except tk.TclError as e:
        sys.exit(f"Could not open a display: {e}\n"
                 "On WSL2 this requires WSLg (Windows 11, or updated WSL on Windows 10).")
    UsageWidget(root)
    root.mainloop()


if __name__ == "__main__":
    main()
