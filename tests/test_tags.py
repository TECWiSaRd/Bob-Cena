"""Checks for room tags (AprilTags). The detector tests need OpenCV; they are skipped without it.
Run:  python3 -m unittest discover -s tests"""
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from home import Home  # noqa: E402
from tags import Tag, TagFinder, TagScanner, TagTracker  # noqa: E402

try:
    import cv2
    import numpy as np
    HAVE_CV = hasattr(cv2, "aruco")
except ImportError:
    HAVE_CV = False

TOKEN = "tok-123456789"


def render(ident, side=120, size=(480, 640), family="DICT_APRILTAG_36h11", angle=0.0, noise=0.0, at=(300, 200), seed=1):
    """A grey 'room' picture with one tag stuck on it, optionally tilted, in perspective, and noisy."""
    d = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, family))
    gen = cv2.aruco.generateImageMarker if hasattr(cv2.aruco, "generateImageMarker") else cv2.aruco.drawMarker
    tag = gen(d, ident, side)
    tag = cv2.copyMakeBorder(tag, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)     # the white margin of a printed sheet
    img = np.full((size[0], size[1], 3), 120, np.uint8)
    h, w = tag.shape
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    a = np.radians(angle)
    dst = np.float32([[at[0] + p[0] * np.cos(a) * (1 - 0.15 * (p[1] / h)) + 0, at[1] + p[1] * np.cos(a) * 0.9] for p in src])
    dst[1][1] += 8 * np.sin(a)
    m = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(cv2.cvtColor(tag, cv2.COLOR_GRAY2BGR), m, (size[1], size[0]), borderValue=(120, 120, 120))
    mask = cv2.warpPerspective(np.full((h, w), 255, np.uint8), m, (size[1], size[0]))
    img = np.where(mask[..., None] > 0, warped, img).astype(np.uint8)
    if noise:
        rng = np.random.default_rng(seed)
        img = np.clip(img.astype(np.int16) + rng.normal(0, noise, img.shape), 0, 255).astype(np.uint8)
    return img


@unittest.skipUnless(HAVE_CV, "OpenCV with aruco isn't installed")
class DetectorTests(unittest.TestCase):
    def setUp(self):
        from tags import TagDetector
        self.det = TagDetector("tag36h11")

    def test_reads_the_number_and_size(self):
        found = self.det.detect(render(7, side=120))
        self.assertEqual([t.id for t in found], [7])
        self.assertGreater(found[0].size_px, 100)
        self.assertLess(found[0].size_px, 140)

    def test_every_room_number_reads_back_correctly(self):
        for ident in (0, 1, 2, 3, 10, 25):
            self.assertEqual([t.id for t in self.det.detect(render(ident))], [ident], ident)

    def test_survives_noise_tilt_and_perspective(self):
        for angle in (0, 15, 30):
            found = self.det.detect(render(4, side=110, angle=angle, noise=12))
            self.assertEqual([t.id for t in found], [4], angle)

    def test_smaller_tags_report_smaller_sizes(self):
        big = self.det.detect(render(3, side=140))[0].size_px
        small = self.det.detect(render(3, side=50))[0].size_px
        self.assertGreater(big, small * 2)

    def test_empty_and_noisy_rooms_have_no_tags(self):
        self.assertEqual(self.det.detect(np.full((480, 640, 3), 120, np.uint8)), [])
        rng = np.random.default_rng(5)
        for _ in range(20):
            self.assertEqual(self.det.detect(rng.integers(0, 255, (480, 640, 3), dtype=np.uint8)), [])

    def test_two_tags_in_one_picture(self):
        a = render(1, side=100, at=(60, 100))
        b = render(2, side=100, at=(380, 100))
        both = cv2.min(a, b)                     # dark parts of either picture win, so both tags show
        self.assertEqual(sorted(t.id for t in self.det.detect(both)), [1, 2])

    def test_a_tag_from_another_family_is_ignored(self):
        self.assertEqual(self.det.detect(render(5, family="DICT_4X4_50")), [])


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.t = [1000.0]
        self.cfg = config.HomeConfig(tag_min_px=40, tag_valid_s=300, tag_max_move_s=20)
        self.tr = TagTracker(self.cfg, lambda: self.t[0])

    def see(self, ident, size=80, moved=0.0, advance=0.3):
        self.t[0] += advance
        self.tr.observe([Tag(ident, size, 0.5)], moved)

    def test_needs_two_sightings(self):
        self.see(3)
        self.assertIsNone(self.tr.current(0)[0])
        self.see(3)
        self.assertEqual(self.tr.current(0)[0], 3)

    def test_two_sightings_far_apart_do_not_count(self):
        self.see(3)
        self.see(3, advance=5)
        self.assertIsNone(self.tr.current(0)[0])

    def test_small_far_away_tags_are_ignored(self):
        for _ in range(5):
            self.see(3, size=20)
        self.assertEqual(self.tr.current(0)[1], "no room tag seen yet")

    def test_the_biggest_tag_wins(self):
        self.t[0] += 0.3
        self.tr.observe([Tag(1, 50, 0.2), Tag(2, 120, 0.7)], 0)
        self.t[0] += 0.3
        self.tr.observe([Tag(1, 50, 0.2), Tag(2, 120, 0.7)], 0)
        self.assertEqual(self.tr.current(0)[0], 2)

    def test_moving_to_another_room_switches_after_two_sightings(self):
        self.see(1)
        self.see(1)
        self.see(2, moved=5)
        self.assertEqual(self.tr.current(5)[0], 1)       # one sighting of a new tag isn't believed yet
        self.see(2, moved=5)
        self.assertEqual(self.tr.current(5)[0], 2)

    def test_trust_expires_with_time(self):
        self.see(1)
        self.see(1)
        self.t[0] += 301
        tag, why = self.tr.current(0)
        self.assertIsNone(tag)
        self.assertIn("min ago", why)

    def test_trust_expires_with_driving_and_refreshes_when_seen_again(self):
        self.see(1)
        self.see(1, moved=0)
        self.assertEqual(self.tr.current(15)[0], 1)
        tag, why = self.tr.current(25)
        self.assertIsNone(tag)
        self.assertIn("driven", why)
        self.see(1, moved=25)
        self.assertEqual(self.tr.current(30)[0], 1)


class FakeClock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


class HomeWithTags(unittest.TestCase):
    def home(self, **kw):
        cfg = config.HomeConfig(enabled=True, url="http://127.0.0.1:9", rooms=["Kitchen", "Living Room"],
                                tags={"1": "Kitchen", "2": "Living Room", "9": "Garage"}, tag_valid_s=300, tag_max_move_s=20, **kw)
        self.moved = [0.0]
        h = Home(cfg, TOKEN)
        h.tracker = TagTracker(cfg, lambda: self.t[0])
        h.moved = lambda: self.moved[0]
        return h

    def setUp(self):
        self.t = [1000.0]

    def confirm(self, h, ident):
        for _ in range(2):
            self.t[0] += 0.3
            h.tracker.observe([Tag(ident, 90, 0.5)], self.moved[0])

    def test_room_from_a_tag(self):
        h = self.home()
        self.confirm(h, 2)
        self.assertEqual(h.where(), ("Living Room", "seen on room tag 2"))

    def test_operator_beats_the_tag(self):
        h = self.home()
        self.confirm(h, 2)
        h.set_manual("kitchen")
        self.assertEqual(h.where()[0], "Kitchen")

    def test_unlisted_and_forbidden_tags_mean_unknown(self):
        h = self.home()
        self.confirm(h, 9)                      # the Garage: a tag exists but Bob isn't allowed to control it
        room, why = h.where()
        self.assertIsNone(room)
        self.assertIn("isn't allowed", why)
        self.confirm(h, 77)                     # a tag nobody listed
        self.assertIn("isn't listed", h.where()[1])

    def test_driving_makes_the_room_unknown_and_lights_refuse(self):
        h = self.home()
        self.confirm(h, 1)
        self.assertEqual(h.where()[0], "Kitchen")
        self.moved[0] = 30
        self.assertIsNone(h.where()[0])
        text, err = h.act("on")
        self.assertTrue(err)
        self.assertIn("don't know which room", text)

    def test_bad_tag_settings_disable_it(self):
        for tags in ({"kitchen": "Kitchen"}, {"1": 5}):
            cfg = config.HomeConfig(enabled=True, rooms=["Kitchen"], tags=tags)
            self.assertFalse(Home(cfg, TOKEN).enabled)

    def test_status_names_the_source(self):
        h = self.home()
        self.confirm(h, 1)
        self.assertIn("room tag 1", " ".join(h.status_lines(80)))


class World:
    """A tiny fake room: Bob turns in place, and a room tag is visible only when he faces about 200 degrees."""

    def __init__(self, tag_at=200.0, tag_id=2):
        self.t = 1000.0
        self.heading = 0.0
        self.moved = 0.0
        self.moves = []
        self.estop = threading.Event()
        self.tag_at, self.tag_id = tag_at, tag_id
        self._until = 0.0
        self._rate = 0.0

    def clock(self):
        return self.t

    def sleep(self, s):
        step = max(s, 0.001)
        if self.t < self._until:                     # the wheels are still running: he turns
            run = min(step, self._until - self.t)
            self.heading = (self.heading + self._rate * run) % 360
            self.moved += run
        self.t += step

    # the drive
    def start(self, left, right, seconds):
        self.moves.append((left, right))
        self._until, self._rate = self.t + seconds, (left - right) / 2 * 180     # degrees per second

    def stop(self):
        self.moves.append("stop")
        self._until = 0.0

    def moved_total(self):
        return self.moved

    # the camera and detector
    def grab_bgr(self):
        return self.heading

    def detect(self, frame):
        if self.tag_at is None:                         # no tag anywhere in this room
            return []
        off = abs((frame - self.tag_at + 180) % 360 - 180)
        return [Tag(self.tag_id, 90, 0.5)] if off < 25 else []


class FinderTests(unittest.TestCase):
    def make(self, tag_at=200.0, **kw):
        self.w = World(tag_at)
        cfg = config.HomeConfig(enabled=True, rooms=["Kitchen", "Living Room"], tags={"2": "Living Room"}, **kw)
        tracker = TagTracker(cfg, self.w.clock)
        finder = TagFinder(cfg, tracker, lambda: self.w, self.w, self.w, clock=self.w.clock, sleep=self.w.sleep)
        return finder, tracker, cfg

    def run_finder(self, finder, seconds=25, allowed=lambda: True):
        finder.active, finder.session = True, finder.session + 1
        finder._run(seconds, allowed)

    def test_turns_until_it_sees_the_tag_then_stops(self):
        finder, tracker, _ = self.make()
        self.run_finder(finder)
        self.assertTrue(finder.found)
        self.assertEqual(finder.result.split(" after")[0], "found room tag 2")
        self.assertEqual(self.w.moves[-1], "stop")
        self.assertEqual(tracker.current(self.w.moved)[0], 2)
        self.assertFalse(finder.active)

    def test_spins_in_place_and_never_drives_forward(self):
        finder, _, _ = self.make()
        self.run_finder(finder)
        for m in self.w.moves:
            if m != "stop":
                self.assertAlmostEqual(m[0], -m[1])

    def test_gives_up_if_there_is_no_tag(self):
        finder, _, _ = self.make(tag_at=None)           # no tag anywhere
        t0 = self.w.t
        self.run_finder(finder, seconds=10)
        self.assertFalse(finder.found)
        self.assertIn("saw no room tag", finder.result)
        self.assertLess(self.w.t - t0, 12)
        self.assertEqual(self.w.moves[-1], "stop")

    def test_emergency_stop_and_pause_end_it(self):
        finder, _, _ = self.make(tag_at=None)
        self.w.estop.set()
        self.run_finder(finder)
        self.assertIn("emergency stop", finder.result)
        self.w.estop.clear()
        finder, _, _ = self.make(tag_at=None)
        self.run_finder(finder, allowed=lambda: False)
        self.assertIn("paused", finder.result)

    def test_each_search_keeps_its_own_outcome(self):
        finder, _, _ = self.make()
        self.run_finder(finder)
        finder.tracker.forget()
        self.w.tag_at = None
        self.run_finder(finder, seconds=5)
        self.assertTrue(finder.outcome(1, 0)[0])
        self.assertFalse(finder.outcome(2, 0)[0])

    def test_start_refuses_without_a_camera_picture_or_while_stopped(self):
        finder, _, _ = self.make()
        self.w.grab_bgr = lambda: None
        self.assertIn("no camera picture", finder.start(10))
        self.w.grab_bgr = lambda: 0.0
        self.w.estop.set()
        self.assertIn("emergency stop", finder.start(10))


class LocateThroughHome(unittest.TestCase):
    def setUp(self):
        self.w = World()
        cfg = config.HomeConfig(enabled=True, rooms=["Kitchen", "Living Room"], tags={"2": "Living Room"})
        self.home = Home(cfg, TOKEN)
        self.home.tracker = TagTracker(cfg, self.w.clock)
        self.home.finder = TagFinder(cfg, self.home.tracker, lambda: self.w, self.w, self.w, clock=self.w.clock, sleep=self.w.sleep)
        self.home.moved = self.w.moved_total

    def test_it_will_not_turn_if_the_room_is_already_known(self):
        self.home.set_manual("kitchen")
        status, text = self.home.locate()
        self.assertEqual(status, "known")
        self.assertIn("already know", text)
        self.assertEqual(self.w.moves, [])

    def test_unknown_room_starts_a_search_and_learns_it(self):
        status, _ = self.home.locate(20)
        self.assertEqual(status, "started")
        self.home.finder.wait(5)
        deadline = time.time() + 5
        while self.home.finder.active and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.home.where()[0], "Living Room")
        self.assertIn("Now you are in the Living Room", self.home.locate_result())

    def test_without_tags_set_up_it_explains(self):
        home = Home(config.HomeConfig(enabled=True, rooms=["Kitchen"]), TOKEN)
        self.assertEqual(home.locate()[0], "error")


class ThroughTheRobot(unittest.TestCase):
    def setUp(self):
        import bob
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        os.environ["HA_TOKEN"] = TOKEN
        cfg = config.Config()
        cfg.stream.enabled = False
        cfg.home = config.HomeConfig(enabled=True, url="http://127.0.0.1:9", rooms=["Kitchen"], tags={"1": "Kitchen"})
        self.ctrl = bob.Controller(cfg, sim=True, paused=True)
        self.ctrl.home.attach_camera(self.ctrl.camera, self.ctrl.drive)
        self.addCleanup(self.ctrl.shutdown)

    def test_find_my_room_is_a_tool_only_when_tags_are_set_up(self):
        self.assertIn("find_my_room", {t["name"] for t in self.ctrl.brain.tools})

    def test_locate_command_explains_when_it_cannot_start(self):
        text = self.ctrl.handle("/locate")
        self.assertIn("can't look", text)                    # the simulated robot has no camera
        self.ctrl.handle("/motion off")
        self.assertIn("disabled", self.ctrl.handle("/locate"))
        self.assertEqual(self.ctrl.handle("/locate off"), "not looking")

    def test_known_room_means_no_turning(self):
        self.ctrl.handle("/where kitchen")
        self.assertIn("already know", self.ctrl.handle("/locate"))
        self.assertEqual(self.ctrl.drive.moved_total(), 0.0)

    def test_claude_tool_is_blocked_by_estop_and_motion_off(self):
        self.ctrl.controls.auto = True
        self.ctrl.brain._gen = self.ctrl.controls.stop_gen
        self.ctrl.handle("/motion off")
        text, err = self.ctrl.brain._dispatch("find_my_room", {})
        self.assertTrue(err)
        self.assertTrue(text.startswith("BLOCKED"))
        self.ctrl.handle("/motion on")
        self.ctrl.drive.estop.set()
        text, err = self.ctrl.brain._dispatch("find_my_room", {})
        self.assertTrue(text.startswith("BLOCKED"))

    def test_claude_is_told_about_the_tool_when_room_unknown(self):
        self.assertIn("find_my_room", self.ctrl.brain._status([], False))


class DriveCounts(unittest.TestCase):
    def test_moved_total_adds_up_real_time_including_a_move_in_progress(self):
        from hardware import Drive
        d = Drive(config.DriveConfig(), sim=True)
        self.addCleanup(d.close)
        self.assertEqual(d.moved_total(), 0.0)
        d.start(0.5, 0.5, 1.0)
        time.sleep(0.2)
        self.assertGreater(d.moved_total(), 0.15)             # counts while still moving
        d.stop()
        total = d.moved_total()
        self.assertGreater(total, 0.15)
        time.sleep(0.1)
        self.assertAlmostEqual(d.moved_total(), total, places=3)    # and stops counting when he stops


class ScannerEndToEnd(unittest.TestCase):
    @unittest.skipUnless(HAVE_CV, "OpenCV with aruco isn't installed")
    def test_a_camera_facing_a_tag_gives_the_room(self):
        frames = [render(2, side=130)]
        cam = type("Cam", (), {"grab_bgr": lambda s: frames[0]})()
        cfg = config.HomeConfig(enabled=True, url="http://127.0.0.1:9", rooms=["Kitchen", "Living Room"],
                                tags={"1": "Kitchen", "2": "Living Room"}, tag_scan_hz=20)
        home = Home(cfg, TOKEN)
        home.attach_camera(cam, type("D", (), {"moved_total": lambda s: 0.0})())
        self.addCleanup(home.stop)
        deadline = time.time() + 5
        while time.time() < deadline and home.where()[0] is None:
            time.sleep(0.05)
        self.assertEqual(home.where()[0], "Living Room")
        report = home.tags_report(frames[0])
        self.assertIn("tag 2", report)
        self.assertIn("counts: the Living Room", report)
        frames[0] = render(2, side=25)
        self.assertIn("too small", home.tags_report(frames[0]))

    def test_missing_aruco_is_reported_not_fatal(self):
        def boom():
            raise RuntimeError("this OpenCV has no aruco module")
        cfg = config.HomeConfig(enabled=True, rooms=["Kitchen"], tags={"1": "Kitchen"})
        tracker = TagTracker(cfg)
        scanner = TagScanner(cfg, tracker, object(), lambda: 0.0, detector_factory=boom)
        scanner.run()
        self.assertIn("no aruco", scanner.problem)


@unittest.skipUnless(HAVE_CV, "OpenCV with aruco isn't installed")
class PrintableTags(unittest.TestCase):
    def test_printed_tags_can_be_read_by_the_detector(self):
        import tag_tools
        from tags import TagDetector
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(tag_tools.main(["make", "5=Kitchen", "6=Living Room", "--cm", "8", "--out", d]), 0)
            files = sorted(Path(d).glob("*.png"))
            self.assertEqual([f.name for f in files], ["tag-5-kitchen.png", "tag-6-living-room.png"])
            for f, ident in zip(files, (5, 6)):
                page = cv2.imread(str(f))
                self.assertEqual(page.shape[:2], (3300, 2550))
                small = cv2.resize(page, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
                self.assertEqual([t.id for t in TagDetector("tag36h11").detect(small)], [ident])

    def test_bad_arguments(self):
        import tag_tools
        self.assertEqual(tag_tools.main(["make", "kitchen"]), 1)


if __name__ == "__main__":
    unittest.main()
