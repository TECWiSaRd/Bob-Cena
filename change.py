"""Think only when something changed: a cheap check that decides whether Bob's next thought is worth paying for.

Each thought sends a camera picture to Claude, so thinking every couple of seconds at a still room wastes tokens.
In "change" mode the brain asks this gate before each thought. It says yes when:

  * somebody wrote to Bob (operator, voice or radio),
  * the picture changed noticeably since the last thought (a person walked in, the light changed, Bob moved),
  * the distance sensor reading moved by a lot, or
  * `idle_max_s` seconds passed with nothing happening (a heartbeat, so he can still act on his goal),

and never sooner than `tick_seconds` after the last thought. Looking at the picture costs no tokens: it is a
small greyscale copy compared on the Pi.
"""
from __future__ import annotations

import time

CELL_STEP = 24          # sample every 24th pixel each way: ~20 x 27 cells for a 640x480 picture
CELL_DELTA = 25         # a cell counts as changed if its brightness moved by more than this (0-255)


def small(frame):
    """A tiny greyscale copy of a BGR picture (numpy array), or None."""
    if frame is None:
        return None
    try:
        return frame[::CELL_STEP, ::CELL_STEP].astype("float32").mean(axis=2) if frame.ndim == 3 \
            else frame[::CELL_STEP, ::CELL_STEP].astype("float32")
    except Exception:
        return None


def changed_percent(a, b) -> float:
    """What percentage of the sampled cells differ noticeably between two small pictures."""
    if a is None or b is None or a.shape != b.shape:
        return 100.0
    return float((abs(a - b) > CELL_DELTA).mean() * 100.0)


class ChangeGate:
    def __init__(self, cfg, clock=time.monotonic, sleep_cfg=None):
        self.cfg, self._clock, self.sleep_cfg = cfg, clock, sleep_cfg
        self.last = None               # when Bob last thought
        self._pic = None               # the picture at that time
        self._dist = None
        self.reason = ""               # why the latest "yes" was given
        self.skipped = 0               # how many looks said "no" (a rough measure of what was saved)

    def check(self, picture, dist_cm, has_mail: bool, force: bool = False, sleeping: bool = False) -> bool:
        now = self._clock()
        why = self._why(now, picture, dist_cm, has_mail, force, sleeping and self.sleep_cfg)
        if why is None:
            self.skipped += 1
            return False
        self.reason, self.last, self._pic, self._dist = why, now, picture, dist_cm
        return True

    def _why(self, now, picture, dist_cm, has_mail, force, rest=None):
        # asleep, the same rules apply but the thresholds are much higher (a big change, or a routine look every so often)
        change_percent = rest.change_percent if rest else self.cfg.change_percent
        idle_max = rest.idle_max_s if rest else self.cfg.idle_max_s
        min_gap = max(self.cfg.tick_seconds, 10.0) if rest else self.cfg.tick_seconds
        if force:
            return "the operator asked for a step"
        if self.last is None:
            return "first look"
        if has_mail:
            return "someone sent you a message"
        if now - self.last < min_gap:
            return None
        pct = changed_percent(self._pic, picture) if picture is not None else 0.0
        if picture is not None and pct >= change_percent:
            return f"the picture changed ({pct:.0f}% of it)"
        if dist_cm is not None and self._dist is not None and abs(dist_cm - self._dist) >= self.cfg.change_distance_cm:
            return f"the distance reading moved ({self._dist:.0f} to {dist_cm:.0f} cm)"
        if now - self.last >= idle_max:
            return f"nothing happened for {idle_max:.0f}s (routine look)"
        return None
