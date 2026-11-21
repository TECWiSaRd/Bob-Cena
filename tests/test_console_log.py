import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import console  # noqa: E402


class FakeScreen:
    """Just enough of a curses window for ConsoleUI.draw()."""

    def getmaxyx(self):
        return 30, 100

    def erase(self):
        pass

    def addnstr(self, *args):
        pass

    def move(self, *args):
        pass

    def clrtoeol(self):
        pass

    def refresh(self):
        pass

    def __getattr__(self, name):
        return lambda *a, **k: None


class FakeController:
    scroll_hint = ""

    def __init__(self):
        import types
        self.drive = types.SimpleNamespace(estop=threading.Event())

    def status_line(self):
        return "status"

    def driving_for(self, who):
        return False


class DrawingWhileOthersLog(unittest.TestCase):
    def test_the_screen_never_crashes_when_another_thread_logs_at_the_same_time(self):
        """A traceback from the Pi: RuntimeError: deque mutated during iteration, in ConsoleUI.draw. It ended Bob's console."""
        buf = console.LogBuffer()
        for i in range(3000):
            buf.lines.append((20, "X", f"line {i}"))
        stop = threading.Event()

        def spam():
            while not stop.is_set():
                buf.lines.append((20, "X", "new line"))

        worker = threading.Thread(target=spam, daemon=True)
        worker.start()
        self.addCleanup(worker.join)
        self.addCleanup(stop.set)
        ui = console.ConsoleUI.__new__(console.ConsoleUI)          # skip curses colour setup
        ui.scr, ui.ctrl, ui.logbuf = FakeScreen(), FakeController(), buf
        ui.buf, ui.scroll, ui.history, ui.hist_idx = "", 0, [], 0
        ui._attr = lambda level, tag: 0
        for _ in range(300):
            ui.draw()


if __name__ == "__main__":
    unittest.main()
