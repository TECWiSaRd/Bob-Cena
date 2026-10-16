"""Self-calibration: Bob measures his own motion with the camera.

Comparing a picture taken before and after a move tells how far the view shifted sideways, and
with the camera's field of view that becomes degrees turned. That gives two things:

  * turn rates: how many degrees per second a spin really produces at a few speeds, which Claude
    then uses to plan turns instead of guessing;
  * straight-line drift: how much the view veers while driving forward, from which a /trim
    correction is worked out.

It needs a reasonably textured scene (a room with furniture is fine; a blank wall is not) and,
for the straight test, about a metre of clear floor. It is started by the operator only.
"""
from __future__ import annotations

import logging
import math
import time

log = logging.getLogger("bob.calibrate")

WIDTH = 320            # pictures are compared at this width
MIN_TRACKS = 20        # fewest well-tracked points needed for a trustworthy answer
SETTLE_S = 0.7         # let the camera and the robot stop shaking before taking the "after" picture


def _gray_small(bgr):
    import cv2
    h, w = bgr.shape[:2]
    return cv2.cvtColor(cv2.resize(bgr, (WIDTH, max(1, int(h * WIDTH / w)))), cv2.COLOR_BGR2GRAY)


def focal_px(fov_deg: float, width_px: float = WIDTH) -> float:
    return (width_px / 2) / math.tan(math.radians(fov_deg) / 2)


def estimate_motion(a_bgr, b_bgr, fov_deg: float):
    """How the view moved from picture A to picture B.

    Returns a dict: yaw_deg (positive = the camera turned LEFT), scale (> 1 when moving forward),
    tracks (how many points agreed; 0 if only the whole-picture shift could be used), or None if the
    scene couldn't be measured.

    Two steps: phase correlation finds the overall sideways shift even when it is large, then the
    shifted picture is aligned and tracked point-by-point for an accurate answer that ignores moving
    objects and the zoom of driving forward."""
    import cv2
    import numpy as np

    a, b = _gray_small(a_bgr), _gray_small(b_bgr)
    h, w = a.shape
    if a.std() < 6 or b.std() < 6:
        return None                                      # a blank wall has nothing to measure against
    window = cv2.createHanningWindow((w, h), cv2.CV_32F)
    (dx, dy), response = cv2.phaseCorrelate(np.float32(a), np.float32(b), window)
    if response < 0.05:
        dx = dy = 0.0   # no clear overall shift (for example the picture zoomed while driving): track points directly
    focal = focal_px(fov_deg, w)
    coarse = {"yaw_deg": math.degrees(math.atan(dx / focal)), "scale": 1.0, "tracks": 0}
    aligned = cv2.warpAffine(b, np.float32([[1, 0, -dx], [0, 1, -dy]]), (w, h), borderMode=cv2.BORDER_REFLECT)
    pts = cv2.goodFeaturesToTrack(a, maxCorners=250, qualityLevel=0.01, minDistance=8)
    if pts is None or len(pts) < MIN_TRACKS:
        return coarse if response >= 0.1 else None
    nxt, ok, _ = cv2.calcOpticalFlowPyrLK(a, aligned, pts, None, winSize=(21, 21), maxLevel=3)
    ok = ok.ravel() == 1
    if ok.sum() < MIN_TRACKS:
        return coarse if response >= 0.1 else None
    src, dst = pts[ok].reshape(-1, 2), nxt[ok].reshape(-1, 2)
    m, inliers = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=2.5)
    if m is None or int(inliers.sum()) < MIN_TRACKS:
        return coarse if response >= 0.1 else None
    cx, cy = w / 2, h / 2
    residual = float((m @ np.array([cx, cy, 1.0]))[0] - cx)        # what the aligned picture still moved
    # Content moving RIGHT in the picture means the camera turned LEFT.
    return {"yaw_deg": math.degrees(math.atan((dx + residual) / focal)),
            "scale": float(math.hypot(m[0, 0], m[1, 0])), "tracks": int(inliers.sum())}


class Calibrator:
    """Runs the turn and straight tests. Blocking: call from a worker thread."""

    def __init__(self, camera, drive, ranger, fov_deg: float, say=log.info, clock=time.monotonic, sleep=time.sleep):
        self.camera, self.drive, self.ranger, self.fov = camera, drive, ranger, fov_deg
        self.say, self._sleep = say, sleep
        self.cancel = False

    def _pic(self):
        """A steady picture: the later of two grabs, to skip a stale buffered frame."""
        self.camera.grab_bgr()
        self._sleep(0.1)
        return self.camera.grab_bgr()

    def _check(self):
        if self.cancel or self.drive.estop.is_set():
            raise RuntimeError("calibration stopped")
        if self.camera.grab_bgr() is None:
            raise RuntimeError("no camera picture")

    def _measure_move(self, left: float, right: float, seconds: float):
        """Drive for `seconds`, and return (what the view did, how long the wheels really ran)."""
        before = self._pic()
        ran = self.drive.move(left, right, seconds)
        self._sleep(SETTLE_S)
        after = self._pic()
        return estimate_motion(before, after, self.fov), ran

    def turn(self, speeds=(0.4, 0.7, 1.0), probe_s=0.15, target_deg=15.0) -> dict:
        """Measure degrees of turn per second at each speed. Returns {"0.4": 38.0, ...}.

        Each speed is tried with a short probe spin first, then with a spin sized to turn about
        `target_deg`, so every measurement stays well inside what the camera can follow."""
        self._check()
        rates = {}
        for speed in speeds:
            pairs, duration = [], probe_s
            for attempt in range(2):
                self._check()
                motion, ran = self._measure_move(-speed, speed, duration)   # spin left
                self.drive.move(speed, -speed, duration)                    # and back, so Bob ends where he started
                self._sleep(SETTLE_S)
                if motion is None:
                    raise RuntimeError("the scene doesn't have enough detail to measure (point Bob at a textured area)")
                yaw = motion["yaw_deg"]
                if abs(yaw) > self.fov * 0.3:
                    raise RuntimeError("the turn was too big to measure safely; lower /speed and try again")
                self.say(f"CALIB speed {speed:g}: {ran:.2f}s turned {yaw:+.1f} deg ({motion['tracks']} points)")
                pairs.append((ran, yaw))
                if attempt == 0:
                    probe_rate = yaw / ran if ran > 0 else 0
                    if probe_rate <= 0.5:
                        raise RuntimeError(f"Bob didn't turn left at speed {speed:g} (a wheel reversed, or too weak to move that briefly?)")
                    duration = max(probe_s, min(0.6, target_deg / probe_rate))
            rate = sum(t * deg for t, deg in pairs) / sum(t * t for t, _ in pairs)   # least-squares slope through the origin
            rates[f"{speed:g}"] = round(rate, 1)
        return rates

    def _drift(self, speed: float, seconds: float) -> float:
        """Yaw drift in degrees per second while driving forward (positive = veers left)."""
        motion, ran = self._measure_move(speed, speed, seconds)
        self.drive.move(-speed, -speed, seconds)                            # return to the start
        self._sleep(SETTLE_S)
        if motion is None:
            raise RuntimeError("couldn't measure the drift (the scene lacks detail)")
        if ran < seconds * 0.6:
            raise RuntimeError(f"Bob was stopped early ({self.drive.stop_reason or 'blocked'}); clear some floor in front of him")
        drift = motion["yaw_deg"] / ran
        self.say(f"CALIB straight: {ran:.1f}s forward, view turned {motion['yaw_deg']:+.1f} deg ({drift:+.1f} deg/s)")
        return drift

    def straight(self, speed: float = 0.6, seconds: float = 1.2, probe: float = 0.08) -> dict:
        """Work out a right-wheel trim that cancels the drift. Returns {"right_trim": x, "left_trim": y, ...}."""
        self._check()
        cfg = self.drive.cfg
        if self.ranger and self.ranger.enabled and (self.ranger.distance_cm or 999) < 80:
            raise RuntimeError("less than 80 cm of clear floor ahead")
        base_left, base_right = cfg.left_trim, cfg.right_trim
        try:
            d0 = self._drift(speed, seconds)
            cfg.right_trim = base_right + probe                              # nudge the right wheel faster and measure again
            d1 = self._drift(speed, seconds)
        finally:
            cfg.left_trim, cfg.right_trim = base_left, base_right
        slope = (d1 - d0) / probe                                            # deg/s of extra left drift per unit of right-wheel trim
        if slope < 3:
            raise RuntimeError(f"the probe changed the drift by too little to be sure ({d0:+.1f} -> {d1:+.1f} deg/s); "
                               "try again on a textured floor and wall")
        fix = base_right - d0 / slope
        fix = max(-0.4, min(0.4, fix))
        return {"left_trim": base_left, "right_trim": round(fix, 3), "drift_before": round(d0, 2), "drift_probe": round(d1, 2)}
