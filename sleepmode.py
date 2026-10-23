"""Sleep mode: at night (or when told) Bob rests, which also saves money.

While asleep he does not wander, thinks only now and then (a long routine look, or when the picture changes a lot), and is
told to stay quiet. Anyone speaking or writing to him wakes him for a couple of minutes, then he drifts off again.
The wheels can still be driven by hand, and the emergency stop works as always.
"""
from __future__ import annotations

import time
from datetime import datetime

from home import parse_clock


class SleepMode:
    def __init__(self, cfg, now=datetime.now, clock=time.monotonic):
        self.cfg, self._now, self._clock = cfg, now, clock
        self.manual: bool | None = None      # True = /sleep on, False = /sleep off, None = follow the schedule
        self.awake_until = 0.0
        self.problem = ""
        self.window: tuple = (None, None)
        if cfg.enabled:
            try:
                self.window = (parse_clock(cfg.start), parse_clock(cfg.end))
            except ValueError as e:
                self.problem = f"[sleep] {e}"

    def scheduled(self) -> bool:
        start, end = self.window
        if not self.cfg.enabled or start is None or end is None:
            return False
        t = (self._now().hour, self._now().minute)
        return (start <= t < end) if start <= end else (t >= start or t < end)

    def asleep(self) -> bool:
        if self.manual is False:
            return False
        resting = self.manual is True or self.scheduled()
        return resting and self._clock() >= self.awake_until

    def poke(self) -> None:
        """Somebody spoke or wrote to him: he is awake for a while."""
        self.awake_until = self._clock() + self.cfg.wake_for_s

    def set(self, arg: str) -> str:
        arg = arg.strip().lower()
        if arg in ("on", "sleep", "now"):
            self.manual, self.awake_until = True, 0.0
        elif arg in ("off", "wake"):
            self.manual = False
        elif arg == "auto":
            self.manual = None
        elif arg:
            return "usage: /sleep on | off | auto"
        return self.describe()

    def describe(self) -> str:
        if self.problem:
            return self.problem
        mode = {True: "forced on", False: "forced off", None: "following the schedule"}[self.manual]
        sched = f"{self.cfg.start}-{self.cfg.end}" if self.cfg.enabled else "no schedule ([sleep] enabled = false)"
        now = "ASLEEP" if self.asleep() else ("resting, but awake for a moment" if (self.manual is True or self.scheduled()) else "awake")
        return f"sleep mode: {now} ({mode}; {sched}). /sleep on|off|auto"
