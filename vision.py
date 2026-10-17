"""Local vision on the Pi: face detection and a fast follow-me reflex.

Claude "thinks" every few seconds, which is too slow to follow a walking person smoothly. While a
follow session is on, this module steers the wheels itself at about 8 times a second from a small
face detector, and Claude is just told how it went. Everything runs on the Pi.

It follows *faces*, so it works while the person is facing Bob and loses them when they turn away.
Every command it sends has a deadline of a fraction of a second, so if this loop ever stalls the
wheels stop by themselves, and the drive layer's obstacle reflex and emergency stop still apply.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("bob.vision")

YUNET_FILE = "face_detection_yunet_2023mar.onnx"
FACE_HEIGHT_M = 0.20  # an adult face is about 20 cm tall; used to turn apparent size into distance


@dataclass
class Face:
    cx: float   # centre, as a fraction of the frame (0 = left edge, 1 = right edge)
    cy: float
    w: float    # size, as a fraction of the frame
    h: float
    score: float = 1.0


class FaceDetector:
    """YuNet (small neural net, robust to angles and lighting) if its model file is present,
    otherwise OpenCV's built-in Haar cascade (frontal faces only)."""

    def __init__(self, model_dir: Path, extra_cascade_dirs=()):
        import cv2

        self.cv2 = cv2
        self._yunet = self._haar = None
        path = Path(model_dir) / YUNET_FILE
        if path.exists() and path.stat().st_size > 100_000 and hasattr(cv2, "FaceDetectorYN"):
            self._yunet = cv2.FaceDetectorYN.create(str(path), "", (320, 240), 0.7, 0.3, 5)
            self.name = "YuNet"
            return
        for folder in [*extra_cascade_dirs, getattr(getattr(cv2, "data", None), "haarcascades", ""),
                       "/usr/share/opencv4/haarcascades/", "/usr/share/opencv/haarcascades/"]:
            xml = Path(folder) / "haarcascade_frontalface_default.xml" if folder else None
            if xml and xml.exists() and hasattr(cv2, "CascadeClassifier"):
                self._haar = cv2.CascadeClassifier(str(xml))
                self.name = "Haar cascade (the YuNet model is missing: run install.sh for better results)"
                return
        raise RuntimeError("no face detector available (install python3-opencv, and the YuNet model)")

    def detect(self, bgr) -> list[Face]:
        cv2 = self.cv2
        h0, w0 = bgr.shape[:2]
        width = 320
        height = max(1, int(h0 * width / w0))
        small = cv2.resize(bgr, (width, height))
        boxes = []
        if self._yunet is not None:
            self._yunet.setInputSize((width, height))
            _, faces = self._yunet.detect(small)
            for f in (faces if faces is not None else []):
                boxes.append((float(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[-1])))
        else:
            gray = cv2.equalizeHist(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
            for x, y, w, h in self._haar.detectMultiScale(gray, 1.2, 4, minSize=(24, 24)):
                boxes.append((float(x), float(y), float(w), float(h), 1.0))
        return [Face((x + w / 2) / width, (y + h / 2) / height, w / width, h / height, s)
                for x, y, w, h, s in boxes if w > 0 and h > 0]


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


class Follower:
    """Turns toward the nearest face and keeps a set distance from it."""

    period = 0.125  # seconds per control step (8 Hz); tests shorten it

    def __init__(self, cfg, fov_deg: float, camera, drive, ranger, detector_factory,
                 clock=time.monotonic, sleep=time.sleep):
        self._clock, self._sleep = clock, sleep  # replaced in tests so the loop can run in simulated time
        self.cfg, self.fov = cfg, fov_deg
        self.camera, self.drive, self.ranger = camera, drive, ranger
        self._detector_factory = detector_factory
        self._detector = None
        self.active = False
        self.mode = "follow"
        self.found = False          # find mode: True once a face was seen
        self.session = 0            # counts every start, so a caller can tell its own session from a later one
        self.outcomes: dict[int, tuple[bool, str]] = {}   # session -> (found a face, result text); the last few
        self.result = ""
        self.steps = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._why = ""

    # ---- operator / brain interface -----------------------------------------------
    def start(self, seconds: float, allowed=lambda: True, mode: str = "follow") -> str | None:
        """Begin following (or, with mode="find", turning on the spot until a face appears).

        Returns an error message, or None if it started."""
        if self.active:
            return "already following" if self.mode == "follow" else "already looking for someone"
        if self.drive.estop.is_set():
            return "the emergency stop is on"
        try:
            if self._detector is None:
                self._detector = self._detector_factory()
                log.info("FOLLOW face detector: %s", self._detector.name)
        except Exception as e:
            return f"face detection isn't available ({e})"
        if self.camera.grab_bgr() is None:
            return "no camera picture (is the camera on?)"
        self._stop.clear()
        self.result = ""
        self.found = False
        self.mode = mode
        self.session += 1
        self.active = True
        run = self._scan if mode == "find" else self._run
        self._thread = threading.Thread(target=run, args=(clamp(seconds, 1, self.cfg.max_seconds), allowed),
                                        name="follower", daemon=True)
        self._thread.start()
        return None

    def stop(self, why: str = "stopped by the operator") -> None:
        self._why = why
        self._stop.set()

    def wait(self, timeout: float | None = None) -> bool:
        if self._thread:
            self._thread.join(timeout)
        return not self.active

    # ---- the control loop ---------------------------------------------------------
    def _goal_height(self, frame) -> float:
        """Apparent face height (fraction of frame height) when the person is distance_m away."""
        h, w = frame.shape[:2]
        vfov = 2 * math.atan(math.tan(math.radians(self.fov) / 2) * h / w)
        return FACE_HEIGHT_M / (2 * self.cfg.distance_m * math.tan(vfov / 2))

    def _pick(self, faces: list[Face], last: Face | None) -> Face | None:
        if not faces:
            return None
        if last is not None:  # stay with the same person when several are visible
            near = min(faces, key=lambda f: abs(f.cx - last.cx) + abs(f.h - last.h))
            if abs(near.cx - last.cx) < 0.3:
                return near
        return max(faces, key=lambda f: f.h)

    def _command(self, face: Face, goal_h: float) -> tuple[float, float]:
        cfg = self.cfg
        err = (face.cx - 0.5) * 2                      # -1 (far left) .. +1 (far right)
        turn = 0.0 if abs(err) < cfg.deadzone else clamp(cfg.turn_gain * err, -1, 1)
        rel = (goal_h - face.h) / goal_h               # > 0: too far away, < 0: too close
        fwd = 0.0 if rel < 0.1 else clamp(cfg.forward_gain * rel, 0, 1)
        if abs(err) > 0.5:
            fwd *= 0.2                                 # mostly turn first when the person is well off to the side
        cm = self.ranger.distance_cm if self.ranger else None
        if cm is not None and cm < 40:
            fwd = 0.0                                  # never close in on something already near
        s = cfg.max_speed
        return clamp((fwd + turn * 0.6) * s, -1, 1), clamp((fwd - turn * 0.6) * s, -1, 1)

    scan_turn_s = 0.4     # find mode: turn this long...
    scan_look_s = 0.7     # ...then hold still this long to look (the picture is blurred while turning)
    scan_settle_s = 0.3   # ...ignoring the first part of the hold, while the camera settles

    def _scan(self, seconds: float, allowed) -> None:
        """Turn slowly on the spot, stopping to look, until a face is seen. Never drives forward."""
        sid = self.session
        t0 = self._clock()
        cycle = self.scan_turn_s + self.scan_look_s
        why, seen_at, looks = "time ran out", None, 0
        log.info("FIND started (looking for a face for up to %.0fs)", seconds)
        try:
            while True:
                now = self._clock()
                if self._stop.is_set():
                    why = self._why
                    break
                if self.drive.estop.is_set():
                    why = "emergency stop"
                    break
                if not allowed():
                    why = "paused by the operator"
                    break
                if now - t0 >= seconds:
                    break
                phase = (now - t0) % cycle
                if phase < self.scan_turn_s:
                    s = clamp(self.cfg.scan_speed, 0.1, 1.0)
                    self.drive.start(s, -s, self.period * 1.6)
                else:
                    self.drive.stop()
                    if phase >= self.scan_turn_s + self.scan_settle_s:
                        frame = self.camera.grab_bgr()
                        if frame is None:
                            why = "lost the camera picture"
                            break
                        looks += 1
                        face = self._pick(self._detector.detect(frame), None)
                        if face is not None:
                            seen_at, why = face, "found a face"
                            break
                self._sleep(max(0.0, self.period - (self._clock() - now)))
        except Exception as e:
            log.exception("Find crashed")
            why = f"error: {e}"
        finally:
            self.drive.stop()
            took = self._clock() - t0
            self.found = seen_at is not None
            if self.found:
                side = (seen_at.cx - 0.5) * 2
                where = "straight ahead" if abs(side) < 0.2 else f"{abs(side) * 100:.0f}% of the way to the {'right' if side > 0 else 'left'} edge"
                self.result = f"found someone after {took:.0f}s: their face is {where}"
            else:
                self.result = f"looked for {took:.0f}s ({looks} looks) and saw no face; ended: {why}"
            self.steps = looks
            self.outcomes[sid] = (self.found, self.result)
            for old in [k for k in self.outcomes if k <= sid - 5]:
                del self.outcomes[old]
            self.active = False
            log.info("FIND ended: %s", self.result)

    def outcome(self, sid: int, timeout: float) -> tuple[bool, str] | None:
        """The result of one particular find session (waits for it), unaffected by any session started later."""
        end = self._clock() + timeout
        while sid not in self.outcomes and self._clock() < end:
            self._sleep(0.05)
        return self.outcomes.get(sid)

    def _run(self, seconds: float, allowed) -> None:
        t0 = self._clock()
        last_seen = t0
        last: Face | None = None
        side = 0
        goal_h = None
        seen = steps = 0
        why = "time ran out"
        log.info("FOLLOW started (up to %.0fs, staying about %.1f m away)", seconds, self.cfg.distance_m)
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
                    why = "paused by the operator"
                    break
                if step_start - t0 >= seconds:
                    break
                frame = self.camera.grab_bgr()
                if frame is None:
                    why = "lost the camera picture"
                    break
                if goal_h is None:
                    goal_h = self._goal_height(frame)
                steps += 1
                face = self._pick(self._detector.detect(frame), last)
                if face is not None:
                    seen += 1
                    last, last_seen = face, step_start
                    side = 1 if face.cx > 0.5 else -1
                    left, right = self._command(face, goal_h)
                    if left or right:
                        self.drive.start(left, right, self.period * 1.6)
                    else:
                        self.drive.stop()
                else:
                    missing = step_start - last_seen
                    if missing > self.cfg.lost_after_s:
                        why = "lost sight of the person" + (f" (last seen on the {'right' if side > 0 else 'left'})" if side else "")
                        break
                    if missing > 0.8 and side:  # look for them where they were last seen
                        s = self.cfg.max_speed * 0.5
                        self.drive.start(side * s, -side * s, self.period * 1.6)
                    else:
                        self.drive.stop()
                self._sleep(max(0.0, self.period - (self._clock() - step_start)))
        except Exception as e:
            log.exception("Follower crashed")
            why = f"error: {e}"
        finally:
            self.drive.stop()
            took = self._clock() - t0
            pct = 100 * seen / steps if steps else 0
            self.steps = steps
            self.result = f"followed for {took:.0f}s (saw a face in {pct:.0f}% of checks); ended: {why}"
            self.active = False
            log.info("FOLLOW ended: %s", self.result)
