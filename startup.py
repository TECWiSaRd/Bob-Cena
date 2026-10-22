"""Start Bob's parts one at a time instead of all at once.

At boot a Pi 4 has four cores and a lot to do: loading the voice and the speech model, the wake word, OpenCV, the
camera, Bluetooth. Doing it all in the same few seconds can leave nothing for SSH and the Wi-Fi driver. So the heavy
parts start in turn, each waiting until the CPU has calmed down (or a time limit passes), with the quick, essential
parts first and the microphone, the heaviest, last. The console is usable straight away.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("bob.startup")


def cpu_busy_percent(sample_s: float = 0.5, read=None, sleep=time.sleep):
    """How busy all the CPU cores were over the last `sample_s` seconds, 0-100, or None if it can't be told here."""
    def stat():
        with open("/proc/stat") as f:
            parts = f.readline().split()[1:]
        values = [int(x) for x in parts]
        idle = values[3] + (values[4] if len(values) > 4 else 0)       # idle + iowait
        return sum(values), idle

    read = read or stat
    try:
        total_a, idle_a = read()
        sleep(sample_s)
        total_b, idle_b = read()
    except (OSError, ValueError, IndexError):
        return None
    total = total_b - total_a
    return None if total <= 0 else 100.0 * (1 - (idle_b - idle_a) / total)


class Stagger:
    def __init__(self, cfg, stop=lambda: False, busy=cpu_busy_percent, clock=time.monotonic, sleep=time.sleep):
        self.cfg, self._stop, self._busy, self._clock, self._sleep = cfg, stop, busy, clock, sleep
        self.started: list[str] = []
        self.done = False

    def wait_calm(self) -> float | None:
        """Wait until the CPU is below the limit twice running, or the time limit passes. Returns the last reading."""
        end = self._clock() + self.cfg.max_wait_s
        calm, last = 0, None
        while self._clock() < end and not self._stop():
            last = self._busy()
            if last is None:                       # can't measure (not Linux): just pause
                self._sleep(self.cfg.step_pause_s)
                return None
            calm = calm + 1 if last < self.cfg.calm_cpu_percent else 0
            if calm >= 2:
                break
        return last

    def run(self, steps) -> None:
        """steps: (name, function) in order. A step that fails is logged and the rest still start."""
        for name, fn in steps:
            if self._stop():
                break
            busy = self.wait_calm()
            if self._stop():
                break
            log.info("Starting %s%s", name, f" (CPU {busy:.0f}% busy)" if busy is not None else "")
            try:
                fn()
                self.started.append(name)
            except Exception:
                log.exception("Starting %s failed", name)
            self._sleep(self.cfg.step_pause_s)
        self.done = True
        log.info("Startup finished")
