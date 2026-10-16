"""Curses console: status bar, live log tail, command line, manual drive."""
from __future__ import annotations

import curses
import logging
import os
import textwrap
from collections import deque

log = logging.getLogger("bob.console")

DRIVE_KEYS = {
    "w": (1, 1), curses.KEY_UP: (1, 1),
    "s": (-1, -1), curses.KEY_DOWN: (-1, -1),
    "a": (-1, 1), curses.KEY_LEFT: (-1, 1),
    "d": (1, -1), curses.KEY_RIGHT: (1, -1),
    "q": (0.35, 1), "e": (1, 0.35),  # arcs
}
TAG_COLORS = {"BOB": 3, "SAY": 3, "YOU": 5, "HEARD": 5, "MOVE": 4, "SOUND": 3, "NOTE": 4, "RADIO": 4}


class LogBuffer(logging.Handler):
    """Keeps recent log lines in memory for the console's live tail."""

    def __init__(self, maxlen: int = 3000):
        super().__init__()
        self.lines: deque[tuple[int, str, str]] = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = self.format(record)
            tag = record.getMessage().split(" ", 1)[0]
        except Exception:
            self.handleError(record)
            return
        for line in text.splitlines():
            self.lines.append((record.levelno, tag, line))


class ConsoleUI:
    def __init__(self, scr, ctrl, logbuf: LogBuffer):
        self.scr, self.ctrl, self.logbuf = scr, ctrl, logbuf
        self.buf = ""
        self.scroll = 0
        self.history: list[str] = []
        self.hist_idx = 0
        curses.curs_set(1)
        scr.keypad(True)
        scr.timeout(100)
        curses.use_default_colors()
        for i, color in enumerate((curses.COLOR_RED, curses.COLOR_YELLOW, curses.COLOR_CYAN,
                                   curses.COLOR_GREEN, curses.COLOR_MAGENTA), start=1):
            curses.init_pair(i, color, -1)
        curses.init_pair(6, curses.COLOR_WHITE, curses.COLOR_RED)

    def loop(self) -> None:
        while not self.ctrl.quit.is_set():
            self.draw()
            try:
                ch = self.scr.get_wch()
            except curses.error:
                continue
            if self.ctrl.drive_mode:
                self.drive_key(ch)
            else:
                self.edit_key(ch)

    # ---- drawing ----------------------------------------------------------
    def draw(self) -> None:
        h, w = self.scr.getmaxyx()
        if h < 5 or w < 20:
            return
        self.scr.erase()
        estop = self.ctrl.drive.estop.is_set()
        bar = curses.color_pair(6) | curses.A_BOLD if estop else curses.A_REVERSE
        self.scr.addnstr(0, 0, self.ctrl.status_line().ljust(w), w - 1, bar)

        rows = h - 3
        wrapped: list[tuple[int, str]] = []
        need = rows + self.scroll
        for level, tag, line in reversed(self.logbuf.lines):
            attr = self._attr(level, tag)
            parts = textwrap.wrap(line, w - 1, subsequent_indent="           ") or [""]
            wrapped[:0] = [(attr, p) for p in parts]
            if len(wrapped) >= need:
                break
        self.scroll = min(self.scroll, max(0, len(wrapped) - rows))
        view = wrapped[max(0, len(wrapped) - rows - self.scroll): len(wrapped) - self.scroll]
        for i, (attr, text) in enumerate(view):
            self.scr.addnstr(1 + i, 0, text, w - 1, attr)

        if self.ctrl.drive_mode:
            hint = " DRIVE: W/S fwd/back  A/D spin  Q/E arc  SPACE stop  X/ESC exit "
        else:
            hint = " SPACE (empty line)=E-STOP  TAB=talk  /help  PgUp/PgDn scroll "
        if self.scroll:
            hint += f" [scrolled {self.scroll}]"
        self.scr.addnstr(h - 2, 0, hint.ljust(w, "-"), w - 1, curses.A_DIM)

        prompt = "> "
        visible = self.buf[-(w - len(prompt) - 2):]
        self.scr.addnstr(h - 1, 0, prompt + visible, w - 1)
        self.scr.move(h - 1, min(w - 2, len(prompt) + len(visible)))
        self.scr.refresh()

    @staticmethod
    def _attr(level: int, tag: str) -> int:
        if level >= logging.ERROR:
            return curses.color_pair(1) | curses.A_BOLD
        if level >= logging.WARNING:
            return curses.color_pair(2)
        if tag in TAG_COLORS:
            return curses.color_pair(TAG_COLORS[tag])
        return curses.A_NORMAL

    # ---- input ------------------------------------------------------------
    def edit_key(self, ch) -> None:
        if ch in ("\n", "\r", curses.KEY_ENTER):
            line, self.buf = self.buf, ""
            if line.strip():
                self.history.append(line)
            self.hist_idx = len(self.history)
            self.scroll = 0
            self.submit(line)
        elif ch == " " and not self.buf:
            self.ctrl.estop("console")
        elif ch == "\t" and not self.buf:
            log.info("%s", self.ctrl.listener.ptt_toggle())
        elif ch in (curses.KEY_BACKSPACE, "\x7f", "\b"):
            self.buf = self.buf[:-1]
        elif ch == "\x1b":
            self.buf = ""
        elif ch == "\x15":  # Ctrl-U
            self.buf = ""
        elif ch == curses.KEY_UP and self.history:
            self.hist_idx = max(0, self.hist_idx - 1)
            self.buf = self.history[self.hist_idx]
        elif ch == curses.KEY_DOWN and self.history:
            self.hist_idx = min(len(self.history), self.hist_idx + 1)
            self.buf = self.history[self.hist_idx] if self.hist_idx < len(self.history) else ""
        elif ch == curses.KEY_PPAGE:
            self.scroll += self.scr.getmaxyx()[0] - 4
        elif ch == curses.KEY_NPAGE:
            self.scroll = max(0, self.scroll - (self.scr.getmaxyx()[0] - 4))
        elif isinstance(ch, str) and ch.isprintable():
            self.buf += ch

    def submit(self, line: str) -> None:
        if line.startswith("/"):
            log.info("> %s", line)
        try:
            out = self.ctrl.handle(line)
        except Exception as e:
            out = f"error: {e}"
        if out:
            log.info("%s", out)

    def drive_key(self, ch) -> None:
        key = ch.lower() if isinstance(ch, str) else ch
        if key in DRIVE_KEYS:
            l, r = DRIVE_KEYS[key]
            # Short pulses that key-repeat keeps extending: release the key and Bob stops.
            self.ctrl.manual(l, r, 0.6)
        elif key == " ":
            self.ctrl.drive.stop()
        elif key in ("x", "\x1b"):
            self.ctrl.drive.stop()
            self.ctrl.drive_mode = False
            log.info("left manual drive - AI still paused, /resume to hand back control")


def run_console(ctrl, logbuf: LogBuffer) -> None:
    os.environ.setdefault("ESCDELAY", "25")  # make ESC respond instantly
    curses.wrapper(lambda scr: ConsoleUI(scr, ctrl, logbuf).loop())
