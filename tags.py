"""Room tags: printed square markers (AprilTag or ArUco) that tell Bob which room he is in.

A tag on the wall by each room's door has its own number. When Bob's camera sees one close up, he knows the room.
He can't feel himself leave a room, so the knowledge expires: after `tag_valid_s` seconds, or once he has driven
`tag_max_move_s` seconds since he last saw a tag. A tag is only believed when it looks big enough (he is close to
it, not looking at the next room's tag through an open door) and has been seen in two pictures in a row.

OpenCV does the detection (its aruco module), so there is nothing extra to install on the Pi.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

log = logging.getLogger("bob.tags")

# name -> the OpenCV dictionary. tag36h11 is the standard AprilTag family and the best at avoiding false matches.
FAMILIES = {"tag36h11": "DICT_APRILTAG_36h11", "tag25h9": "DICT_APRILTAG_25h9", "aruco4x4_50": "DICT_4X4_50"}


@dataclass
class Tag:
    id: int
    size_px: float    # average side length in the picture
    cx: float         # centre, as a fraction of the picture width


class TagDetector:
    def __init__(self, family: str = "tag36h11"):
        import cv2
        if not hasattr(cv2, "aruco"):
            raise RuntimeError("this OpenCV has no aruco module (try: sudo apt-get install python3-opencv)")
        if family not in FAMILIES:
            raise ValueError(f"unknown tag family {family}")
        self.cv2, self.family = cv2, family
        dictionary = getattr(cv2.aruco, FAMILIES[family])
        if hasattr(cv2.aruco, "ArucoDetector"):                 # OpenCV 4.7 and newer
            self._detect = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(dictionary),
                                                   cv2.aruco.DetectorParameters()).detectMarkers
        else:                                                    # older OpenCV, as on Raspberry Pi OS Bookworm
            d = cv2.aruco.getPredefinedDictionary(dictionary)
            p = cv2.aruco.DetectorParameters_create()
            self._detect = lambda img: cv2.aruco.detectMarkers(img, d, parameters=p)

    def detect(self, bgr) -> list[Tag]:
        gray = self.cv2.cvtColor(bgr, self.cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
        corners, ids, _ = self._detect(gray)
        if ids is None:
            return []
        width = gray.shape[1]
        out = []
        for quad, ident in zip(corners, ids.flatten()):
            pts = quad.reshape(4, 2)
            sides = [((pts[i] - pts[(i + 1) % 4]) ** 2).sum() ** 0.5 for i in range(4)]
            out.append(Tag(int(ident), float(sum(sides) / 4), float(pts[:, 0].mean() / width)))
        return out


class TagTracker:
    """Decides which tag, if any, Bob can still trust. No threads, no camera: easy to test."""

    def __init__(self, cfg, clock=time.monotonic):
        self.cfg, self._clock = cfg, clock
        self.id: int | None = None
        self.at = 0.0              # when the tag was last (confidently) seen
        self.moved_at = 0.0        # how long Bob had driven in total at that moment
        self._pending: tuple[int, float] | None = None
        self._lock = threading.Lock()   # the background scanner and a search both feed it

    def observe(self, tags: list[Tag], moved_total: float) -> None:
        with self._lock:
            self._observe(tags, moved_total)

    def _observe(self, tags: list[Tag], moved_total: float) -> None:
        now = self._clock()
        big = [t for t in tags if t.size_px >= self.cfg.tag_min_px]
        if not big:
            return
        best = max(big, key=lambda t: t.size_px)
        if self.id == best.id:                                  # already trusted: just keep it fresh
            self.at, self.moved_at = now, moved_total
            self._pending = None
        elif self._pending and self._pending[0] == best.id and now - self._pending[1] <= 1.5:
            self.id, self.at, self.moved_at, self._pending = best.id, now, moved_total, None
            log.info("TAG room tag %d seen", best.id)
        else:
            self._pending = (best.id, now)                      # needs a second sighting to be believed

    def current(self, moved_total: float) -> tuple[int | None, str]:
        """(tag number, '') while it can be trusted, else (None, the reason)."""
        with self._lock:
            tag, at, moved_at = self.id, self.at, self.moved_at
        if tag is None:
            return None, "no room tag seen yet"
        age = self._clock() - at
        if age > self.cfg.tag_valid_s:
            return None, f"the last room tag was seen {age / 60:.0f} min ago"
        moved = moved_total - moved_at
        if moved > self.cfg.tag_max_move_s:
            return None, f"he has driven {moved:.0f}s since he last saw a room tag"
        return tag, ""

    def forget(self) -> None:
        with self._lock:
            self.id, self._pending = None, None


class TagScanner(threading.Thread):
    """Looks for tags a few times a second whenever the camera is on."""

    def __init__(self, cfg, tracker: TagTracker, camera, moved_total, detector_factory=None):
        super().__init__(name="tags", daemon=True)
        self.cfg, self.tracker, self.camera, self.moved_total = cfg, tracker, camera, moved_total
        self._factory = detector_factory or (lambda: TagDetector(cfg.tag_family))
        self.halt = threading.Event()
        self.detector = None
        self.problem = ""

    def run(self) -> None:
        try:
            self.detector = self._factory()
        except Exception as e:
            self.problem = f"room tags unavailable: {e}"
            log.warning(self.problem)
            return
        log.info("TAG scanning for room tags (%s)", self.cfg.tag_family)
        period = 1.0 / max(0.5, self.cfg.tag_scan_hz)
        while not self.halt.wait(period):
            try:
                frame = self.camera.grab_bgr()
                if frame is not None:
                    self.tracker.observe(self.detector.detect(frame), self.moved_total())
            except Exception as e:
                log.warning("tag scan failed (%s)", e)
                self.halt.wait(2.0)

    def stop(self) -> None:
        self.halt.set()


class TagFinder:
    """Turns slowly on the spot, stopping to look, until a room tag is seen. Never drives forward."""

    period = 0.125       # seconds per step; tests shorten it
    turn_s = 0.4         # turn this long...
    hold_s = 1.0         # ...then hold still this long and look (the picture blurs while turning)
    settle_s = 0.3       # ...ignoring the first part of the hold, while the camera settles

    def __init__(self, cfg, tracker, detector_getter, camera, drive, clock=time.monotonic, sleep=time.sleep):
        self.cfg, self.tracker, self._detector, self.camera, self.drive = cfg, tracker, detector_getter, camera, drive
        self._clock, self._sleep = clock, sleep
        self.active = False
        self.found = False
        self.result = ""
        self.session = 0
        self.outcomes: dict[int, tuple[bool, str]] = {}
        self._stop = threading.Event()
        self._why = ""
        self._thread: threading.Thread | None = None

    def start(self, seconds: float, allowed=lambda: True) -> str | None:
        """Begin looking. Returns an error message, or None if it started."""
        if self.active:
            return "already looking"
        if self.drive.estop.is_set():
            return "the emergency stop is on"
        if self._detector() is None:
            return "the tag scanner isn't running (is the camera on, and does OpenCV have the aruco module?)"
        if self.camera.grab_bgr() is None:
            return "no camera picture (is the camera on?)"
        self._stop.clear()
        self.result, self.found = "", False
        self.session += 1
        self.active = True
        self._thread = threading.Thread(target=self._run, args=(max(1.0, min(seconds, 120.0)), allowed),
                                        name="tag-finder", daemon=True)
        self._thread.start()
        return None

    def stop(self, why: str = "stopped by the operator") -> None:
        self._why = why
        self._stop.set()

    def wait(self, timeout: float | None = None) -> bool:
        if self._thread:
            self._thread.join(timeout)
        return not self.active

    def outcome(self, sid: int, timeout: float):
        """The result of one particular search (waits for it), unaffected by any search started later."""
        end = self._clock() + timeout
        while sid not in self.outcomes and self._clock() < end:
            self._sleep(0.05)
        return self.outcomes.get(sid)

    def _run(self, seconds: float, allowed) -> None:
        sid = self.session
        t0 = self._clock()
        cycle = self.turn_s + self.hold_s
        why, looks, tag = "time ran out", 0, None
        log.info("LOCATE started (turning to look for a room tag, up to %.0fs)", seconds)
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
                if phase < self.turn_s:
                    s = max(0.1, min(1.0, self.cfg.tag_search_speed))
                    self.drive.start(s, -s, self.period * 1.6)
                else:
                    self.drive.stop()
                    if phase >= self.turn_s + self.settle_s:
                        frame = self.camera.grab_bgr()
                        if frame is None:
                            why = "lost the camera picture"
                            break
                        looks += 1
                        self.tracker.observe(self._detector().detect(frame), self.drive.moved_total())
                        current, _ = self.tracker.current(self.drive.moved_total())
                        if current is not None and self.tracker.at >= t0:     # confirmed during this search
                            tag, why = current, "found a room tag"
                            break
                self._sleep(max(0.0, self.period - (self._clock() - now)))
        except Exception as e:
            log.exception("Tag search crashed")
            why = f"error: {e}"
        finally:
            self.drive.stop()
            took = self._clock() - t0
            self.found = tag is not None
            self.result = (f"found room tag {tag} after {took:.0f}s" if self.found
                           else f"turned for {took:.0f}s ({looks} looks) and saw no room tag; ended: {why}")
            self.outcomes[sid] = (self.found, self.result)
            for old in [k for k in self.outcomes if k <= sid - 5]:
                del self.outcomes[old]
            self.active = False
            log.info("LOCATE ended: %s", self.result)
