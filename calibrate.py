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
MIN_TRACKS = 8         # fewest well-tracked points needed for a trustworthy answer
RANSAC_PX = 3.0        # followed points this close to the best-fit movement count as agreeing with it
SETTLE_S = 1.0         # let the camera and the robot stop shaking before taking the "after" picture
TRIES = 3              # a straight-line run that can't be measured is repeated this many times before giving up
SHORTER = 0.7          # ...and each repeat drives for this fraction of the previous time (the view changes less)
MIN_RUN_S = 0.4        # but never shorter than this


def _gray_small(bgr):
    import cv2
    h, w = bgr.shape[:2]
    return cv2.cvtColor(cv2.resize(bgr, (WIDTH, max(1, int(h * WIDTH / w)))), cv2.COLOR_BGR2GRAY)


def focal_px(fov_deg: float, width_px: float = WIDTH) -> float:
    return (width_px / 2) / math.tan(math.radians(fov_deg) / 2)


def estimate_motion(a_bgr, b_bgr, fov_deg: float):
    """How the view moved from picture A to picture B, or None if the scene couldn't be measured (see explain_motion for why).

    Returns a dict: yaw_deg (positive = the camera turned LEFT), scale (> 1 when moving forward),
    tracks (how many points agreed; 0 if only the whole-picture shift could be used).

    Two steps: phase correlation finds the overall sideways shift even when it is large, then the
    shifted picture is aligned and tracked point-by-point for an accurate answer that ignores moving
    objects and the zoom of driving forward."""
    return explain_motion(a_bgr, b_bgr, fov_deg)[0]


def explain_motion(a_bgr, b_bgr, fov_deg: float):
    """Like estimate_motion, but returns (result, reason): the reason is a plain sentence saying why there is no result."""
    import cv2
    import numpy as np

    a, b = _gray_small(a_bgr), _gray_small(b_bgr)
    h, w = a.shape
    if a.std() < 6 or b.std() < 6:
        return None, f"the picture is too plain or too dark (contrast {min(a.std(), b.std()):.1f}, needs 6)"
    window = cv2.createHanningWindow((w, h), cv2.CV_32F)
    (dx, dy), response = cv2.phaseCorrelate(np.float32(a), np.float32(b), window)
    if response < 0.05:
        dx = dy = 0.0   # no clear overall shift (for example the picture zoomed while driving): track points directly
    focal = focal_px(fov_deg, w)
    coarse = {"yaw_deg": math.degrees(math.atan(dx / focal)), "scale": 1.0, "tracks": 0}
    fallback = (coarse, "") if response >= 0.1 else None
    aligned = cv2.warpAffine(b, np.float32([[1, 0, -dx], [0, 1, -dy]]), (w, h), borderMode=cv2.BORDER_REFLECT)
    pts = cv2.goodFeaturesToTrack(a, maxCorners=250, qualityLevel=0.01, minDistance=8)
    if pts is None or len(pts) < MIN_TRACKS:
        return fallback or (None, f"only {0 if pts is None else len(pts)} corners to track in the picture (needs {MIN_TRACKS}): point him at something with more detail")
    nxt, ok, _ = cv2.calcOpticalFlowPyrLK(a, aligned, pts, None, winSize=(21, 21), maxLevel=3)
    ok = ok.ravel() == 1
    if ok.sum() < MIN_TRACKS:
        return fallback or (None, f"only {int(ok.sum())} points could be followed between the two pictures (needs {MIN_TRACKS}): "
                                  "the picture may be blurred or the view changed too much")
    src, dst = pts[ok].reshape(-1, 2), nxt[ok].reshape(-1, 2)
    m, inliers = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=RANSAC_PX)
    if m is None or int(inliers.sum()) < MIN_TRACKS:
        return fallback or (None, f"only {0 if m is None else int(inliers.sum())} followed points agreed on how the view moved (needs {MIN_TRACKS}): "
                                  "something may have moved in front of the camera, or part of Bob (a wheel, a cable) is in its view")
    cx, cy = w / 2, h / 2
    residual = float((m @ np.array([cx, cy, 1.0]))[0] - cx)        # what the aligned picture still moved
    # Content moving RIGHT in the picture means the camera turned LEFT.
    return {"yaw_deg": math.degrees(math.atan((dx + residual) / focal)),
            "scale": float(math.hypot(m[0, 0], m[1, 0])), "tracks": int(inliers.sum())}, ""


class Calibrator:
    """Runs the turn and straight tests. Blocking: call from a worker thread."""

    def __init__(self, camera, drive, ranger, fov_deg: float, say=log.info, clock=time.monotonic, sleep=time.sleep, save_failed=None):
        self.camera, self.drive, self.ranger, self.fov = camera, drive, ranger, fov_deg
        self.save_failed = save_failed      # a folder: pictures of a run that couldn't be measured are saved there, to see what the camera saw
        self.say, self._sleep = say, sleep
        self.cancel = False
        self.last_reason = ""       # why the last measurement gave no answer

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
        result, self.last_reason = explain_motion(before, after, self.fov)
        if result is None and self.save_failed:
            self._save_pair(before, after)
        return result, ran

    def _save_pair(self, before, after) -> None:
        """Keep the pictures of a failed measurement (only the latest pair, so the folder never fills up)."""
        try:
            import cv2
            from pathlib import Path
            folder = Path(self.save_failed)
            folder.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(folder / "calib-failed-before.jpg"), before)
            cv2.imwrite(str(folder / "calib-failed-after.jpg"), after)
            self.say(f"CALIB: saved the pictures it couldn't measure to {folder}/calib-failed-before.jpg and calib-failed-after.jpg")
        except Exception as e:
            log.warning("couldn't save the failed calibration pictures (%s)", e)

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
                    raise RuntimeError(f"couldn't measure the turn: {self.last_reason} (point Bob at a textured area)")
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

    def _drift(self, speed: float, seconds: float, forward: bool = True) -> float:
        """Heading drift in degrees per second while driving forward (or, with forward=False, backward). Positive = his heading turns left.

        A run that can't be measured (a blurred or too-plain picture, or the view changing too much) is repeated, each time a little
        shorter. After every run Bob drives back to where he started, for as long as he went out."""
        way = 1 if forward else -1
        label = "straight" if forward else "backing up"
        reason = ""
        run_s = seconds
        for attempt in range(1, TRIES + 1):
            self._check()
            motion, ran = self._measure_move(way * speed, way * speed, run_s)
            self.drive.move(-way * speed, -way * speed, run_s)             # return to the start (for as long as he went out)
            self._sleep(SETTLE_S)
            if ran < run_s * 0.6:
                raise RuntimeError(f"Bob was stopped early ({self.drive.stop_reason or 'blocked'}); clear some floor "
                                   f"{'in front of' if forward else 'behind'} him")
            if motion is not None:
                drift = motion["yaw_deg"] / ran
                self.say(f"CALIB {label}: {ran:.1f}s {'forward' if forward else 'backward'}, view turned {motion['yaw_deg']:+.1f} deg "
                         f"({drift:+.1f} deg/s, {motion['tracks']} points)")
                return drift
            reason = self.last_reason
            if attempt < TRIES:
                run_s = max(MIN_RUN_S, run_s * SHORTER)             # the view may have changed too much: a shorter run changes it less
                self.say(f"CALIB {label}: couldn't measure that run ({reason}); trying again, shorter ({attempt}/{TRIES}, {run_s:.1f}s)")
        raise RuntimeError(f"couldn't measure the drift{'' if forward else ' backing up'}: {reason}")

    def _solve(self, speed: float, seconds: float, probe: float, forward: bool) -> dict:
        """Find the right-wheel trim (for going forward, or the back_ trim for going backward) that cancels the drift."""
        cfg = self.drive.cfg
        key = "right_trim" if forward else "back_right_trim"
        base = getattr(cfg, key)
        try:
            d0 = self._drift(speed, seconds, forward)
            setattr(cfg, key, base + probe)                                  # nudge the right wheel faster and measure again
            d1 = self._drift(speed, seconds, forward)
        finally:
            setattr(cfg, key, base)
        slope = (d1 - d0) / probe                                            # deg/s of extra drift per unit of right-wheel trim
        # A faster right wheel turns his heading LEFT going forward, but RIGHT going backward, so the slope has opposite signs.
        if (slope if forward else -slope) < 3:
            raise RuntimeError(f"the probe changed the {'' if forward else 'backing-up '}drift by too little (or the wrong way) to be sure "
                               f"({d0:+.1f} -> {d1:+.1f} deg/s); try again on a textured floor and wall")
        fix = max(-0.4, min(0.4, base - d0 / slope))
        return {key: round(fix, 3), "drift_before": round(d0, 2), "drift_probe": round(d1, 2)}

    def straight(self, speed: float = 0.6, seconds: float = 1.2, probe: float = 0.08, reverse: bool = True, forward: bool = True) -> dict:
        """Work out the right-wheel trims that cancel the drift going forward, and (with reverse=True) going backward too.

        Returns {"left_trim", "right_trim", "drift_before", "drift_probe"} and, when reversing, "back_left_trim", "back_right_trim",
        "back_drift_before". If only the backward part can't be measured, the forward answer is still returned, with "back_error".
        With forward=False only the backward part is done (the forward trims are returned as they are, and without "drift_before")."""
        self._check()
        cfg = self.drive.cfg
        if not forward and not reverse:
            raise RuntimeError("nothing to calibrate")
        if forward and self.ranger and self.ranger.enabled and (self.ranger.distance_cm or 999) < 80:
            raise RuntimeError("less than 80 cm of clear floor ahead")
        out = {"left_trim": cfg.left_trim, "right_trim": cfg.right_trim}
        if forward:
            fwd = self._solve(speed, seconds, probe, forward=True)
            out.update(right_trim=fwd["right_trim"], drift_before=fwd["drift_before"], drift_probe=fwd["drift_probe"])
        if reverse:
            out["back_left_trim"] = cfg.back_left_trim
            out["back_right_trim"] = cfg.back_right_trim                      # unchanged unless the backward part works
            try:
                back = self._solve(speed, seconds, probe, forward=False)
                out["back_right_trim"] = back["back_right_trim"]
                out["back_drift_before"] = back["drift_before"]
            except RuntimeError as e:
                if not forward or self.cancel or self.drive.estop.is_set():
                    raise                                                     # backing up was all he was asked to do: say it failed
                out["back_error"] = str(e)
                self.say(f"CALIB backing up: {e}")
        return out
