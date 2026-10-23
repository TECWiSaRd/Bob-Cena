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
from tags import Tag, TagFinder, TagGoer, TagScanner, TagTracker  # noqa: E402

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

    def test_a_tag_room_written_as_an_area_id_still_matches(self):
        cfg = config.HomeConfig(enabled=True, url="http://127.0.0.1:9", rooms=["adams_room"], tags={"3": "Adam's Room"})
        h = Home(cfg, TOKEN)
        h.tracker = TagTracker(cfg, lambda: self.t[0])
        self.moved = [0.0]
        h.moved = lambda: self.moved[0]
        self.confirm(h, 3)
        self.assertEqual(h.where()[0], "adams_room")

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


class FakeScanner:
    """Stands in for the tag scanner: every look returns the next list of tags."""

    def __init__(self, looks):
        self.looks, self.problem = list(looks), ""
        self.camera = type("Cam", (), {"grab_bgr": lambda s: object()})()
        self.detector = type("Det", (), {"detect": lambda d, f: self.looks.pop(0) if self.looks else []})()

    def stop(self):
        pass


class MeasureTests(unittest.TestCase):
    def home_with(self, looks):
        home = Home(config.HomeConfig(enabled=True, rooms=["Kitchen"], tags={"1": "Kitchen"}), TOKEN)
        home.scanner = FakeScanner(looks)
        return home

    def test_takes_the_middle_of_the_readings(self):
        sizes = [58, 60, 61, 59, 60, 62, 60, 59, 61, 60, 90, 30]          # two odd readings are ignored by the median
        size, text = self.home_with([[Tag(1, s, 0.5)] for s in sizes]).measure_tag(sleep=lambda s: None)
        self.assertAlmostEqual(size, 60, delta=2)
        self.assertIn("Measured tag 1", text)

    def test_refuses_if_the_tag_is_rarely_seen(self):
        looks = [[Tag(1, 60, 0.5)]] + [[]] * 11
        size, text = self.home_with(looks).measure_tag(sleep=lambda s: None)
        self.assertIsNone(size)
        self.assertIn("only 1 of 12", text)

    def test_refuses_if_several_tags_keep_changing(self):
        looks = [[Tag(i % 3, 60, 0.5)] for i in range(12)]
        size, text = self.home_with(looks).measure_tag(sleep=lambda s: None)
        self.assertIsNone(size)
        self.assertIn("aim him at just one", text)

    def test_without_a_scanner_it_explains(self):
        home = Home(config.HomeConfig(enabled=True, rooms=["Kitchen"], tags={"1": "Kitchen"}), TOKEN)
        self.assertIsNone(home.measure_tag()[0])


class SavedMinimum(unittest.TestCase):
    def setUp(self):
        import bob
        self.bob = bob
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.old = bob.TUNING
        bob.TUNING = Path(self.dir.name) / "tuning.json"          # never touch the real tuning.json
        self.addCleanup(setattr, bob, "TUNING", self.old)
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        os.environ["HA_TOKEN"] = TOKEN

    def robot(self):
        cfg = config.Config()
        cfg.stream.enabled = False
        cfg.home = config.HomeConfig(enabled=True, url="http://127.0.0.1:9", rooms=["Kitchen"], tags={"1": "Kitchen"})
        ctrl = self.bob.Controller(cfg, sim=True, paused=True)
        self.addCleanup(ctrl.shutdown)
        return ctrl

    def test_measured_value_is_ninety_percent_and_survives_a_restart(self):
        ctrl = self.robot()
        ctrl.home.scanner = FakeScanner([[Tag(1, 60, 0.5)]] * 12)
        real = ctrl.home.measure_tag
        ctrl.home.measure_tag = lambda: real(sleep=lambda s: None)
        text = ctrl.handle("/tags min")
        self.assertIn("Minimum set to 54 px", text)
        self.assertEqual(ctrl.cfg.home.tag_min_px, 54)
        self.assertEqual(ctrl.home.cfg.tag_min_px, 54)                 # the live setting the tracker reads
        self.assertEqual(self.bob.json.loads(self.bob.TUNING.read_text())["tag_min_px"], 54)
        again = self.robot()                                           # a restart reads it back
        self.assertEqual(again.cfg.home.tag_min_px, 54)

    def test_typed_values_are_limited_and_reset_goes_back_to_config(self):
        ctrl = self.robot()
        ctrl.handle("/tags min 5")
        self.assertEqual(ctrl.cfg.home.tag_min_px, 15)
        ctrl.handle("/tags min 9999")
        self.assertEqual(ctrl.cfg.home.tag_min_px, 400)
        ctrl.handle("/tags min 33")
        self.assertIn("40 px", ctrl.handle("/tags min reset"))
        self.assertEqual(ctrl.cfg.home.tag_min_px, 40)
        self.assertNotIn("tag_min_px", self.bob.json.loads(self.bob.TUNING.read_text()))
        self.assertIn("usage", ctrl.handle("/tags min banana"))
        self.assertIn("usage", ctrl.handle("/tags nonsense"))

    def test_saving_the_minimum_keeps_trims_and_calibration(self):
        ctrl = self.robot()
        ctrl.handle("/trim left 0.05")
        ctrl.handle("/tags min 50")
        ctrl.handle("/minduty 0.3")
        data = self.bob.json.loads(self.bob.TUNING.read_text())
        self.assertEqual((data["left_trim"], data["dc_min_duty"], data["tag_min_px"]), (0.05, 0.3, 50))

    def test_bad_saved_values_are_ignored(self):
        for bad in ("big", True, None, [1]):
            self.bob.TUNING.write_text(self.bob.json.dumps({"tag_min_px": bad}))
            self.assertEqual(self.robot().cfg.home.tag_min_px, 40, bad)

    def test_it_will_not_measure_while_moving(self):
        ctrl = self.robot()
        ctrl.drive.start(0.5, 0.5, 1.0)
        self.assertIn("hold still", ctrl.handle("/tags min"))
        ctrl.drive.stop()


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



class GoWorld:
    """Bob in a flat world: a tag at a fixed bearing and distance. He turns, then creeps forward; the tag looks bigger up close."""

    FOV = 62.0

    def __init__(self, bearing=40.0, distance=2.0, tag_id=1, obstacle_at=None):
        self.t = 1000.0
        self.heading, self.dist, self.bearing, self.tag_id = 0.0, distance, bearing, tag_id
        self.obstacle_at = obstacle_at
        self.moved = 0.0
        self.moves = []
        self.estop = threading.Event()
        self.stop_reason = ""
        self._until, self._l, self._r = 0.0, 0.0, 0.0

    def clock(self):
        return self.t

    def sleep(self, s):
        step = max(s, 0.001)
        if self.t < self._until:
            run = min(step, self._until - self.t)
            self.heading = (self.heading + (self._l - self._r) / 2 * 180 * run) % 360
            forward = (self._l + self._r) / 2
            if forward > 0:
                self.dist = max(0.05, self.dist - forward * 0.5 * run)
            self.moved += run
        self.t += step

    def start(self, left, right, seconds):
        self.moves.append((round(left, 2), round(right, 2)))
        self.stop_reason = ""
        if (left + right) / 2 > 0 and self.obstacle_at is not None and self.dist <= self.obstacle_at:
            self.stop_reason = "obstacle 12 cm ahead - refused to drive forward"
            return False
        self._until, self._l, self._r = self.t + seconds, left, right
        return True

    def stop(self):
        self.moves.append("stop")
        self._until = 0.0

    def moved_total(self):
        return self.moved

    def grab_bgr(self):
        return (self.heading, self.dist)

    def detect(self, frame):
        heading, dist = frame
        off = (self.bearing - heading + 180) % 360 - 180            # + means the tag is to his right
        if abs(off) > self.FOV / 2:
            return []
        return [Tag(self.tag_id, 60.0 / dist, 0.5 + off / self.FOV)]


class GoerTests(unittest.TestCase):
    def make(self, **world):
        self.w = GoWorld(**world)
        cfg = config.HomeConfig(enabled=True, rooms=["Kitchen"], tags={"1": "Kitchen", "5": "Hallway"})
        tracker = TagTracker(cfg, self.w.clock)
        goer = TagGoer(cfg, tracker, lambda: self.w, self.w, self.w, clock=self.w.clock, sleep=self.w.sleep)
        return goer, tracker

    def go(self, goer, hops=(1,), seconds=90, allowed=lambda: True):
        goer.active, goer.session, goer.target = True, goer.session + 1, "Kitchen"
        goer._run(list(hops), seconds, allowed)

    def test_it_finds_the_tag_turns_to_it_and_drives_up_to_it(self):
        goer, tracker = self.make(bearing=100.0, distance=2.5)
        self.go(goer)
        self.assertTrue(goer.arrived, goer.result)
        self.assertLessEqual(self.w.dist, 60.0 / 180 + 0.05)
        self.assertEqual(self.w.moves[-1], "stop")
        self.assertEqual(tracker.current(self.w.moved)[0], 1)         # and he now knows he is in the Kitchen

    def test_it_never_drives_forward_without_seeing_the_tag(self):
        goer, _ = self.make(bearing=100.0, distance=2.5)
        looked = []
        real = self.w.start

        def watch(left, right, seconds):
            if (left + right) / 2 > 0:
                looked.append(bool(self.w.detect(self.w.grab_bgr())))
            return real(left, right, seconds)

        self.w.start = watch
        self.go(goer)
        self.assertTrue(looked and all(looked))

    def test_it_stays_slow_and_steers_towards_the_tag(self):
        goer, _ = self.make(bearing=10.0, distance=2.0)
        self.go(goer)
        forward = [m for m in self.w.moves if m != "stop" and (m[0] + m[1]) / 2 > 0]
        self.assertTrue(forward)
        self.assertTrue(all(max(m) <= 0.35 * 1.31 for m in forward))

    def test_an_obstacle_ends_it_and_it_says_so(self):
        goer, _ = self.make(bearing=5.0, distance=2.0, obstacle_at=1.2)
        self.go(goer)
        self.assertFalse(goer.arrived)
        self.assertIn("blocked", goer.result)
        self.assertIn("obstacle", goer.result)
        self.assertEqual(self.w.moves[-1], "stop")

    def test_no_tag_anywhere_gives_up_after_a_circle(self):
        goer, _ = self.make(bearing=100.0)
        self.w.bearing = 100.0
        self.w.tag_id = 7                                              # a different tag: the Kitchen's never appears
        self.go(goer)
        self.assertFalse(goer.arrived)
        self.assertIn("couldn't find tag 1", goer.result)

    def test_a_route_goes_through_each_tag_in_turn(self):
        goer, tracker = self.make(bearing=20.0, distance=1.5, tag_id=5)
        order = []
        real = self.w.detect

        def detect(frame):
            tags = real(frame)
            if self.w.dist <= 0.32 and self.w.tag_id == 5:               # arrived at the hallway tag: the kitchen tag appears
                order.append("hall")
                self.w.tag_id, self.w.dist, self.w.bearing = 1, 1.5, 200.0
            return tags

        self.w.detect = detect
        self.go(goer, hops=(5, 1))
        self.assertTrue(goer.arrived, goer.result)
        self.assertEqual(order, ["hall"])

    def test_emergency_stop_pause_and_stop_end_it(self):
        goer, _ = self.make(bearing=100.0, distance=3.0)
        self.w.estop.set()
        self.go(goer)
        self.assertIn("emergency stop", goer.result)
        goer, _ = self.make(bearing=100.0, distance=3.0)
        self.go(goer, allowed=lambda: False)
        self.assertIn("paused", goer.result)

    def test_start_refuses_without_a_camera_tags_or_while_stopped(self):
        goer, _ = self.make()
        self.assertIn("no tag", goer.start("Kitchen", [], 60))
        self.w.estop.set()
        self.assertIn("emergency stop", goer.start("Kitchen", [1], 60))


class GotoThroughHome(unittest.TestCase):
    def setUp(self):
        self.w = GoWorld(bearing=30.0, distance=2.0)
        self.cfg = config.HomeConfig(enabled=True, url="http://127.0.0.1:9", rooms=["Kitchen", "Living Room"],
                                     tags={"1": "Kitchen", "2": "Living Room", "5": "Hallway"}, paths={"Kitchen": [5, 1]})
        self.h = Home(self.cfg, TOKEN)
        self.h.tracker = TagTracker(self.cfg, self.w.clock)
        self.h.goer = TagGoer(self.cfg, self.h.tracker, lambda: self.w, self.w, self.w, clock=self.w.clock, sleep=self.w.sleep)

    def test_unknown_rooms_list_the_ones_that_work(self):
        status, text = self.h.goto("garage")
        self.assertEqual(status, "error")
        self.assertIn("Hallway, Kitchen, Living Room", text)

    def test_names_match_loosely_and_a_configured_route_is_used(self):
        self.h.goer.start = lambda room, hops, seconds, allowed=None: self.__dict__.update(hops=hops, room=room)
        self.assertEqual(self.h.goto("kitchen")[0], "started")
        self.assertEqual((self.hops, self.room), ([5, 1], "Kitchen"))
        self.h.goto("LIVING  room")
        self.assertEqual(self.hops, [2])

    def test_already_there_means_no_driving(self):
        for _ in range(2):
            self.w.t += 0.3
            self.h.tracker.observe([Tag(1, 90, 0.5)], 0.0)
        self.h.moved = lambda: 0.0
        self.h.tracker._clock = self.w.clock
        status, text = self.h.goto("Kitchen")
        self.assertEqual(status, "known")

    def test_a_bad_route_disables_home_assistant_with_a_clear_reason(self):
        bad = config.HomeConfig(enabled=True, rooms=["Kitchen"], tags={"1": "Kitchen"}, paths={"Kitchen": [9]})
        h = Home(bad, TOKEN)
        self.assertFalse(h.enabled)
        self.assertIn("paths", h.problem)

    def test_not_at_a_house_without_the_feature(self):
        h = Home(config.HomeConfig(enabled=True, rooms=["Kitchen"], tags={"1": "Kitchen"}, wifi=["Adam's House"]), TOKEN)
        h.wifi_reader = lambda: "Rylan Home"
        h.goer = object()
        self.assertEqual(h.goto("Kitchen")[0], "error")


class GotoThroughTheRobot(unittest.TestCase):
    def setUp(self):
        import bob
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        cfg = config.Config()
        cfg.stream.enabled = False
        cfg.home.enabled, cfg.home.url = True, "http://127.0.0.1:9"
        cfg.home.rooms, cfg.home.tags = ["Kitchen"], {"1": "Kitchen"}
        os.environ["HA_TOKEN"] = TOKEN
        self.addCleanup(os.environ.pop, "HA_TOKEN", None)
        self.ctrl = bob.Controller(cfg, sim=True, paused=False)
        self.addCleanup(self.ctrl.shutdown)
        self.w = GoWorld()
        self.ctrl.home.tracker = TagTracker(cfg.home, self.w.clock)
        self.ctrl.home.goer = TagGoer(cfg.home, self.ctrl.home.tracker, lambda: self.w, self.w, self.w,
                                      clock=self.w.clock, sleep=self.w.sleep)

    def test_go_to_room_is_a_tool_only_when_tags_are_set_up(self):
        self.assertIn("go_to_room", {t["name"] for t in self.ctrl.brain.tools})

    def test_commands_explain_and_respect_the_overrides(self):
        self.assertIn("Kitchen", self.ctrl.handle("/goto"))
        self.ctrl.handle("/motion off")
        self.assertIn("movement is disabled", self.ctrl.handle("/goto kitchen"))
        self.ctrl.handle("/motion on")
        self.ctrl.handle("/sleep on")
        self.assertIn("asleep", self.ctrl.handle("/goto kitchen"))
        self.ctrl.handle("/sleep off")
        self.ctrl.drive.emergency_stop()
        self.assertIn("E-stop", self.ctrl.handle("/goto kitchen"))

    def test_claudes_tool_is_blocked_by_estop_sleep_and_motion_off(self):
        block = type("B", (), {"name": "go_to_room", "type": "tool_use", "input": {"room": "Kitchen"}, "id": "x"})()
        self.ctrl.handle("/sleep on")
        self.assertIn("sleep time", self.ctrl.brain._run_tool(block)["content"])
        self.ctrl.handle("/sleep off")
        self.ctrl.handle("/motion off")
        self.assertIn("disabled movement", self.ctrl.brain._run_tool(block)["content"])


if __name__ == "__main__":
    unittest.main()
