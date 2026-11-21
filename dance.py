"""A little dance: Bob wiggles, spins, takes steps and plays sounds, and stays roughly where he is.

Every forward step is followed by the same step backward (and every arc by its mirror image), and every spin by the opposite spin, so he
ends up about where he started. It only ever sends short wheel commands, so the wheels stop by themselves if this thread dies. The drive's own
limits apply to every step (speed cap, emergency stop, the distance sensor refusing forward moves). It ends when the time is up, when it is
stopped, or when anything else takes over the wheels.
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger("bob.dance")

NAMES = ("party", "wiggle", "spin", "steps")
GAP_S = 0.1            # a short stop between moves, so the wheels never reverse in one go
SLICE_S = 0.05         # how often a move checks whether it should end


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def routine(name: str, speed: float) -> list[tuple]:
    """The moves of one pass of a dance. Each move that goes somewhere comes with its own way back, as one unit that is never cut in half by the clock:
    ("spin", secs): a right spin, then an equal left spin; ("pair", left, right, secs): drive out, then the same back. ("pause", secs); ("sound", name).
    A "pair" always starts with its forward leg, so a distance-sensor refusal skips the whole pair."""
    s = clamp(speed, 0.1, 1.0)
    wiggle = [("sound", "chirp")] + [("spin", 0.3)] * 4 + [("pause", 0.3)]
    spin = [("sound", "happy"), ("spin", 1.0), ("pause", 0.3)]
    steps = [("pair", s, s, 0.5), ("pair", s, s, 0.5), ("pause", 0.2), ("sound", "beep"),
             ("pair", s, s * 0.35, 0.7), ("pair", s * 0.35, s, 0.7), ("pause", 0.3)]
    return {"wiggle": wiggle, "spin": spin, "steps": steps,
            "party": [("sound", "startup")] + wiggle + steps + spin + [("sound", "happy")]}[name]


class Dancer:
    def __init__(self, cfg, drive, sound=None, clock=time.monotonic, sleep=time.sleep):
        self._clock, self._sleep = clock, sleep
        self.cfg, self.drive, self.sound = cfg, drive, sound      # sound: a function taking a sound name (played off the dancing thread)
        self.active = False
        self.name = ""
        self.result = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._why = ""

    # ---- operator interface --------------------------------------------------------
    def start(self, name: str, seconds: float | None = None, allowed=lambda: True) -> str | None:
        """Begin dancing. Returns an error message, or None if it started."""
        if self.active:
            return f"already dancing ({self.name})"
        if name not in NAMES:
            return f"unknown dance (try: {', '.join(NAMES)})"
        if self.drive.estop.is_set():
            return "the emergency stop is on"
        seconds = clamp(self.cfg.default_seconds if seconds is None else seconds, 3.0, self.cfg.max_seconds)
        self._stop.clear()
        self.name, self.result = name, ""
        self.active = True
        self._thread = threading.Thread(target=self._run, args=(name, seconds, allowed), name="dancer", daemon=True)
        self._thread.start()
        return None

    def stop(self, why: str = "stopped by the operator") -> None:
        self._why = why
        self._stop.set()

    def wait(self, timeout: float | None = None) -> bool:
        if self._thread:
            self._thread.join(timeout)
        return not self.active

    # ---- the dance -----------------------------------------------------------------
    def _should_end(self, allowed) -> str | None:
        if self._stop.is_set():
            return self._why
        if self.drive.estop.is_set():
            return "emergency stop"
        if not allowed():
            return "paused, or someone took over the driving"
        return None

    def _hold(self, secs: float, until: float, allowed) -> str | None:
        """Wait `secs` (checking for a stop all the time). Returns why the dance should end, or None."""
        end = min(self._clock() + secs, until)
        while True:
            why = self._should_end(allowed)
            if why:
                return why
            left = end - self._clock()
            if left <= 0:
                return None
            self._sleep(min(SLICE_S, left))

    def _play(self, name: str) -> None:
        if self.cfg.sounds and self.sound is not None:
            try:
                self.sound(name)
            except Exception as e:
                log.warning("Dance sound failed (%s)", e)

    def _leg(self, left: float, right: float, secs: float, allowed) -> str | None:
        """One leg of a move: run the wheels for `secs` (ignoring the clock, so a unit is never cut in half) and stop. Returns why to end, or None."""
        self.drive.start(left, right, secs * 1.5)
        why = self._hold(secs, float("inf"), allowed)
        self.drive.stop()
        return why

    def _run(self, name: str, seconds: float, allowed) -> None:
        t0 = self._clock()
        until = t0 + seconds
        why = "time was up"
        passes = skipped = 0
        speed = clamp(self.cfg.speed, 0.1, 1.0)
        log.info("DANCE started: %s for up to %.0fs", name, seconds)
        try:
            ended = None
            while not ended and self._clock() < until:
                passes += 1
                for move in routine(name, speed):
                    if self._clock() >= until:
                        break
                    ended = self._should_end(allowed)
                    if ended:
                        break
                    kind = move[0]
                    if kind == "sound":
                        self._play(move[1])
                    elif kind == "pause":
                        self.drive.stop()
                        ended = self._hold(move[1], float("inf"), allowed)
                    elif kind == "spin":
                        secs = move[1]
                        ended = self._leg(speed, -speed, secs, allowed) or self._hold(GAP_S, float("inf"), allowed) \
                            or self._leg(-speed, speed, secs, allowed)
                    else:                                                # "pair": out, then back
                        _, left, right, secs = move
                        if not self.drive.start(left, right, secs * 1.5):
                            skipped += 1                                 # something close ahead: skip the out-and-back, not just half of it
                            ended = self._hold(GAP_S, float("inf"), allowed)
                        else:
                            ended = self._hold(secs, float("inf"), allowed)
                            self.drive.stop()
                            ended = ended or self._hold(GAP_S, float("inf"), allowed) or self._leg(-left, -right, secs, allowed)
                    if ended:
                        break
                    ended = self._hold(GAP_S, float("inf"), allowed)
                    if ended:
                        break
            if ended:
                why = ended
        except Exception as e:
            log.exception("Dancer crashed")
            why = f"error: {e}"
        finally:
            self.drive.stop()
            took = self._clock() - t0
            note = f"; skipped {skipped} step{'s' * (skipped != 1)} because something was close ahead" if skipped else ""
            self.result = f"danced the {name} for {took:.0f}s ({passes} pass{'es' * (passes != 1)}){note}; ended: {why}"
            self.active = False
            log.info("DANCE ended: %s", self.result)
