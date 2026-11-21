"""What colours is the camera looking at, and where?

Runs on the Pi with OpenCV and nothing else: no network, no model file. The picture is shrunk, turned into hue / saturation / value
(HSV, which separates "which colour" from "how bright"), and each named colour gets a mask. For every colour we keep the biggest
connected patch, so a red ball is found even if there is a little red elsewhere, and report how much of the picture it fills and which
way it is (a bearing from the camera's field of view, negative = left).

It only looks. Nothing here drives the wheels; /color and Claude's see_colors tool just describe the picture.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

log = logging.getLogger("bob.colors")

SIZE = (160, 120)           # the picture is shrunk to this first: fast, and smooths out noise

# Hue ranges in OpenCV's units (0-179, a half-turn of the colour wheel). Red wraps round, so it has two.
HUES = {
    "red": [(0, 9), (170, 179)],
    "orange": [(10, 21)],
    "yellow": [(22, 33)],
    "green": [(34, 84)],
    "cyan": [(85, 99)],
    "blue": [(100, 129)],
    "purple": [(130, 150)],
    "pink": [(151, 169)],
}
GREYS = ("white", "black")
NAMES = tuple(HUES) + GREYS


@dataclass
class ColorBlob:
    name: str
    percent: float      # how much of the picture the biggest patch of this colour fills
    total: float        # how much of the picture is this colour altogether
    cx: float           # the patch's centre as a fraction of the picture (0 = left edge, 1 = right edge)
    cy: float           # 0 = top, 1 = bottom
    w: float
    h: float
    bearing: float      # degrees from straight ahead; negative = left


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def direction_words(bearing: float) -> str:
    if abs(bearing) < 6:
        return "straight ahead"
    return f"{abs(bearing):.0f} degrees to the {'right' if bearing > 0 else 'left'}"


def height_words(cy: float) -> str:
    return "high up" if cy < 0.34 else "low down" if cy > 0.66 else "in the middle"


class ColorFinder:
    def __init__(self, cfg, fov_deg: float):
        import cv2
        import numpy as np
        self.cv2, self.np, self.cfg, self.fov = cv2, np, cfg, fov_deg

    def _hsv(self, bgr):
        cv2 = self.cv2
        small = cv2.resize(bgr, SIZE, interpolation=cv2.INTER_AREA)
        return cv2.cvtColor(cv2.GaussianBlur(small, (5, 5), 0), cv2.COLOR_BGR2HSV)

    def _mask(self, hsv, name: str):
        np, cfg = self.np, self.cfg
        h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
        if name == "white":
            return (s <= cfg.white_saturation) & (v >= cfg.white_value)
        if name == "black":
            return v <= cfg.black_value
        colourful = (s >= cfg.min_saturation) & (v >= cfg.min_value)
        hue = np.zeros(h.shape, dtype=bool)
        for lo, hi in HUES[name]:
            hue |= (h >= lo) & (h <= hi)
        return colourful & hue

    def analyze(self, bgr, only: str | None = None) -> list[ColorBlob]:
        """Every colour with a patch big enough to count (or just [only]), biggest first."""
        cv2, np, cfg = self.cv2, self.np, self.cfg
        hsv = self._hsv(bgr)
        total_px = float(hsv.shape[0] * hsv.shape[1])
        kernel = np.ones((3, 3), np.uint8)
        blobs = []
        for name in ([only] if only else NAMES):
            mask = self._mask(hsv, name).astype(np.uint8)
            all_px = float(mask.sum())
            if all_px / total_px * 100 < cfg.min_percent:
                continue
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)          # drop single speckles
            count, _, stats, centres = cv2.connectedComponentsWithStats(mask, connectivity=8)
            if count < 2:
                continue
            best = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
            area = float(stats[best, cv2.CC_STAT_AREA])
            if area / total_px * 100 < cfg.min_percent:
                continue
            cx, cy = float(centres[best][0]) / hsv.shape[1], float(centres[best][1]) / hsv.shape[0]
            blobs.append(ColorBlob(
                name=name, percent=area / total_px * 100, total=all_px / total_px * 100, cx=cx, cy=cy,
                w=float(stats[best, cv2.CC_STAT_WIDTH]) / hsv.shape[1], h=float(stats[best, cv2.CC_STAT_HEIGHT]) / hsv.shape[0],
                bearing=(cx - 0.5) * self.fov))
        return sorted(blobs, key=lambda b: -b.percent)

    def centre(self, bgr) -> tuple[int, int, int, str]:
        """The hue, saturation and value of the middle of the picture, and what we would call it: for tuning the settings."""
        hsv = self._hsv(bgr)
        h, w = hsv.shape[:2]
        patch = hsv[h // 2 - 4:h // 2 + 4, w // 2 - 4:w // 2 + 4].reshape(-1, 3)
        hh, ss, vv = (int(round(float(x))) for x in self.np.median(patch, axis=0))
        one = self.np.array([[[hh, ss, vv]]], dtype=self.np.uint8)
        for name in NAMES:
            if bool(self._mask(one, name)[0, 0]):
                return hh, ss, vv, name
        return hh, ss, vv, "no colour name (too dull or too dim: see min_saturation and min_value)"


def describe(blobs: list[ColorBlob], limit: int = 5) -> str:
    """Plain words for a list of blobs."""
    if not blobs:
        return "no clear colours (nothing fills enough of the picture)"
    lines = []
    for b in blobs[:limit]:
        lines.append(f"{b.name}: biggest patch fills {b.percent:.0f}% of the picture, {direction_words(b.bearing)}, "
                     f"{height_words(b.cy)}" + (f" ({b.total:.0f}% in all)" if b.total - b.percent >= 3 else ""))
    return "; ".join(lines)


class ColorFollower:
    """Turns toward a named colour and drives up to it, for as long as it is left running: it ends only when somebody stops it
    (or the emergency stop, a pause, /motion off, manual driving, or a lost camera picture ends it for them).

    Every wheel command lasts a fraction of a second, so if this thread ever died the wheels would stop by themselves. The drive's own
    limits (speed cap, emergency stop, the distance sensor refusing forward moves) apply to every step."""

    period = 0.125          # seconds per control step (8 Hz); tests shorten it
    no_picture_s = 2.0      # give up when the camera has given no picture for this long
    lost_grace_s = 0.5      # a colour that vanishes for less than this is just a missed picture: keep still, don't start searching
    scan_burst_s = 0.25     # searching: turn this long...
    scan_pause_s = 0.25     # ...then hold still this long, so the camera gets a sharp picture before the next turn

    def __init__(self, cfg, finder, camera, drive, clock=time.monotonic, sleep=time.sleep, ranger=None):
        self._clock, self._sleep = clock, sleep
        self.cfg, self.finder, self.camera, self.drive, self.ranger = cfg, finder, camera, drive, ranger
        self.active = False
        self.color = ""
        self.seen = False          # is the colour in view right now
        self.result = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._why = ""

    # ---- operator interface --------------------------------------------------------
    def start(self, name: str, allowed=lambda: True) -> str | None:
        """Begin following `name`. Returns an error message, or None if it started."""
        if self.active:
            return f"already following {self.color}"
        if name not in NAMES:
            return f"unknown colour (try: {', '.join(NAMES)})"
        if self.drive.estop.is_set():
            return "the emergency stop is on"
        if self.camera.grab_bgr() is None:
            return "no camera picture (is the camera on?)"
        self._stop.clear()
        self.color, self.result, self.seen = name, "", False
        self.active = True
        self._thread = threading.Thread(target=self._run, args=(allowed,), name="color-follower", daemon=True)
        self._thread.start()
        return None

    def stop(self, why: str = "stopped by the operator") -> None:
        self._why = why
        self._stop.set()

    def wait(self, timeout: float | None = None) -> bool:
        if self._thread:
            self._thread.join(timeout)
        return not self.active

    # ---- the control loop ----------------------------------------------------------
    def _command(self, blob: ColorBlob) -> tuple[float, float, float]:
        """(left, right, turn) wheel speeds for a patch: turn toward it, and come closer until it fills follow_percent."""
        cfg = self.cfg
        speed = clamp(cfg.follow_speed, 0.0, 1.0)
        err = (blob.cx - 0.5) * 2                                   # -1 (far left) .. 1 (far right)
        turn = 0.0 if abs(err) < cfg.follow_deadzone else clamp(cfg.follow_turn_gain * err, -1.0, 1.0) * speed
        fwd = 0.0
        if blob.percent < cfg.follow_percent and abs(err) < 0.6:    # only drive ahead when roughly facing it
            fwd = speed * clamp((cfg.follow_percent - blob.percent) / cfg.follow_percent, 0.3, 1.0)
        left, right = fwd + turn, fwd - turn                        # a patch on the right (turn > 0) spins him right
        peak = max(abs(left), abs(right))
        if peak > speed:
            left, right = left / peak * speed, right / peak * speed
        return left, right, turn

    def _near_enough(self) -> bool:
        """Has the distance sensor (if there is one, and follow_distance_cm is set) said he is close enough?"""
        limit = self.cfg.follow_distance_cm
        if not limit or self.ranger is None:
            return False
        d = self.ranger.distance_cm
        return d is not None and d <= limit

    def _run(self, allowed) -> None:
        t0 = self._clock()
        last_seen = t0
        side = 0                    # which way it was last seen (1 = right, -1 = left); 0 = not seen yet
        no_frame_since = None
        blocked_until = 0.0
        seen_steps = steps = 0
        why = "stopped"
        log.info("COLOR FOLLOW started: %s (until stopped)", self.color)
        try:
            while True:
                step_start = self._clock()
                if self._stop.is_set():
                    why = self._why
                    break
                if self.drive.estop.is_set():
                    why = "emergency stop"
                    break
                if not allowed():
                    why = "paused, or someone took over the driving"
                    break
                frame = self.camera.grab_bgr()
                if frame is None:
                    no_frame_since = no_frame_since if no_frame_since is not None else step_start
                    self.drive.stop()
                    if step_start - no_frame_since >= self.no_picture_s:
                        why = "lost the camera picture"
                        break
                    self._sleep(self.period)
                    continue
                no_frame_since = None
                steps += 1
                blobs = self.finder.analyze(frame, only=self.color)
                if blobs:
                    blob = blobs[0]
                    seen_steps += 1
                    if not self.seen:
                        log.info("COLOR FOLLOW: found %s", self.color)
                    self.seen, last_seen = True, step_start
                    side = 1 if blob.cx > 0.5 else -1
                    left, right, turn = self._command(blob)
                    if self._near_enough() and left + right > 0.05:
                        left, right = turn, -turn                   # close enough by the distance sensor: only turn, don't come closer
                    if step_start < blocked_until and left + right > 0.05:
                        left, right = turn, -turn                   # the distance sensor said no a moment ago: only turn
                    if left or right:
                        if not self.drive.start(left, right, self.period * 1.6) and left + right > 0.05:
                            blocked_until = step_start + 1.0        # forward refused (something close ahead): don't ask every step
                            if turn:
                                self.drive.start(turn, -turn, self.period * 1.6)
                            else:
                                self.drive.stop()
                    else:
                        self.drive.stop()
                else:
                    if self.seen:
                        log.info("COLOR FOLLOW: lost %s, turning to look for it", self.color)
                    self.seen = False
                    missing = step_start - last_seen
                    limit = self.cfg.follow_search_s                # 0 = keep looking for as long as it takes
                    if side and missing <= self.lost_grace_s:
                        self.drive.stop()                           # probably one missed picture
                    elif limit and missing > limit:
                        self.drive.stop()                           # gave up: wait still and keep watching
                    else:
                        cycle = self.scan_burst_s + self.scan_pause_s
                        if missing % cycle < self.scan_burst_s:     # turn a little, hold still for a sharp picture, repeat
                            s = clamp(self.cfg.follow_search_speed or self.cfg.follow_speed * 0.5, 0.0, 1.0)   # 0 = automatic
                            way = side or 1                         # toward where it went; never seen: turn right
                            self.drive.start(way * s, -way * s, self.period * 1.6)
                        else:
                            self.drive.stop()
                self._sleep(max(0.0, self.period - (self._clock() - step_start)))
        except Exception as e:
            log.exception("Colour follower crashed")
            why = f"error: {e}"
        finally:
            self.drive.stop()
            took = self._clock() - t0
            pct = 100 * seen_steps / steps if steps else 0
            self.result = f"followed {self.color} for {took:.0f}s (saw it in {pct:.0f}% of checks); ended: {why}"
            self.seen = False
            self.active = False
            log.info("COLOR FOLLOW ended: %s", self.result)
