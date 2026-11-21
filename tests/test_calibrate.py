import math
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import cv2
    import numpy as np
except ImportError:                                  # a Mac venv without OpenCV: these tests are skipped
    cv2 = np = None

import calibrate  # noqa: E402

FOV = 62.0
W, H = 640, 480


def scene(seed=1):
    """A busy picture: lots of rectangles, circles and speckle, like a bookshelf."""
    rng = np.random.default_rng(seed)
    img = np.full((H, W * 2, 3), 120, np.uint8)
    for _ in range(260):
        x, y = int(rng.integers(0, W * 2 - 40)), int(rng.integers(0, H - 40))
        w, h = int(rng.integers(8, 40)), int(rng.integers(8, 40))
        colour = tuple(int(c) for c in rng.integers(0, 255, 3))
        if rng.random() < 0.5:
            cv2.rectangle(img, (x, y), (x + w, y + h), colour, -1)
        else:
            cv2.circle(img, (x + w // 2, y + h // 2), w // 2, colour, -1)
    noise = rng.integers(-18, 18, img.shape, dtype=np.int16)
    return np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)


BIG = scene() if cv2 is not None else None


def view(yaw_deg):
    """What the camera sees when it has turned `yaw_deg` to the LEFT (content slides right)."""
    focal = (W / 2) / math.tan(math.radians(FOV) / 2)
    dx = focal * math.tan(math.radians(yaw_deg))
    x0 = int(round(W / 2 - dx))
    return BIG[:, x0:x0 + W].copy()


def blank():
    return np.full((H, W, 3), 128, np.uint8)


@unittest.skipIf(cv2 is None, "needs OpenCV and numpy")
class MeasuringMotion(unittest.TestCase):
    def test_a_known_turn_is_measured_in_both_directions(self):
        for yaw in (-6.0, -2.0, 1.5, 5.0):
            got = calibrate.estimate_motion(view(0), view(yaw), FOV)
            self.assertIsNotNone(got, f"yaw {yaw}")
            self.assertAlmostEqual(got["yaw_deg"], yaw, delta=0.4)

    def test_a_blank_wall_says_why(self):
        got, why = calibrate.explain_motion(blank(), blank(), FOV)
        self.assertIsNone(got)
        self.assertIn("too plain", why)
        self.assertIsNone(calibrate.estimate_motion(blank(), blank(), FOV))

    def test_the_reason_is_empty_when_it_works(self):
        got, why = calibrate.explain_motion(view(0), view(3), FOV)
        self.assertIsNotNone(got)
        self.assertEqual(why, "")


class FakeWorld:
    """Bob in a room: driving forward turns the view by (DRIFT + SLOPE * right_trim) degrees per second."""

    DRIFT = 3.9          # veers left, like the +3.9 deg/s the real Bob measured
    SLOPE = 45.0         # extra LEFT drift per unit of right-wheel trim (a faster right wheel pushes him further left)

    def __init__(self, blank_after=(), back_drift=None):
        self.yaw = 0.0
        self.cfg = SimpleNamespace(left_trim=0.0, right_trim=0.0, back_left_trim=0.0, back_right_trim=0.0)
        self.back_drift = back_drift                # None: backing up simply undoes the forward drift (no separate reverse behaviour)
        self.estop = threading.Event()
        self.stop_reason = ""
        self.moves = []
        self.pictures = 0
        self.blank_pictures = set(blank_after)      # picture numbers (1-based) that come out blank

    def rate(self):
        return self.DRIFT + self.SLOPE * self.cfg.right_trim

    def move(self, left, right, seconds):
        self.moves.append((left, right, seconds))
        if left > 0 and right > 0:
            self.yaw += self.rate() * seconds
        elif left < 0 and right < 0:
            if self.back_drift is None:
                self.yaw -= self.rate() * seconds    # driving back undoes the forward drift
            else:                                    # his own reverse behaviour: a faster right wheel turns his heading RIGHT going backward
                self.yaw += (self.back_drift - self.SLOPE * self.cfg.back_right_trim) * seconds
        return seconds

    def grab_bgr(self):
        self.pictures += 1
        return blank() if self.pictures in self.blank_pictures else view(self.yaw)


@unittest.skipIf(cv2 is None, "needs OpenCV and numpy")
class TheStraightTest(unittest.TestCase):
    def calibrator(self, world):
        self.said = []
        return calibrate.Calibrator(world, world, None, FOV, say=self.said.append, sleep=lambda s: None)

    def test_it_finds_the_trim_that_cancels_the_drift(self):
        world = FakeWorld()
        out = self.calibrator(world).straight(reverse=False)
        self.assertAlmostEqual(out["right_trim"], -world.DRIFT / world.SLOPE, delta=0.02)
        self.assertEqual((world.cfg.left_trim, world.cfg.right_trim), (0.0, 0.0))   # the test never leaves a trim behind

    def test_a_run_that_cannot_be_measured_is_repeated(self):
        # grabs: 1 = the opening check; then per run 1 check + 2 'before' + 2 'after'. So the first run uses 2-6 and the
        # second (the probe) run's 'after' pictures are 10 and 11: make those blank so that run cannot be measured.
        world = FakeWorld(blank_after={10, 11})
        cal = self.calibrator(world)
        out = cal.straight(reverse=False)
        self.assertAlmostEqual(out["right_trim"], -world.DRIFT / world.SLOPE, delta=0.02)
        self.assertTrue([m for m in self.said if "trying again" in m and "too plain" in m], self.said)
        self.assertEqual(len(world.moves), 6)                         # first drift pair, a repeated pair, then the probe pair
        self.assertAlmostEqual(world.yaw, 0.0, delta=0.01)            # and he ended up where he started

    def test_giving_up_says_why_and_brings_him_back(self):
        world = FakeWorld(blank_after=set(range(1, 100)))
        cal = self.calibrator(world)
        with self.assertRaises(RuntimeError) as cm:
            cal.straight()
        self.assertIn("couldn't measure the drift", str(cm.exception))
        self.assertIn("too plain", str(cm.exception))                 # the reason, not just "the scene lacks detail"
        self.assertEqual(len(world.moves), 2 * calibrate.TRIES)       # every attempt drove back
        self.assertAlmostEqual(world.yaw, 0.0, delta=0.01)

    def test_a_failed_run_is_repeated_shorter(self):
        world = FakeWorld(blank_after={10, 11})                       # the probe run's first try can't be measured
        out = self.calibrator(world).straight(reverse=False)
        times = [m[2] for m in world.moves]
        self.assertEqual(times[:2], [1.2, 1.2])                       # the first pair as asked
        self.assertEqual(times[2:4], [1.2, 1.2])                      # the probe pair that failed
        self.assertAlmostEqual(times[4], 1.2 * calibrate.SHORTER)     # its repeat is shorter
        self.assertAlmostEqual(out["right_trim"], -world.DRIFT / world.SLOPE, delta=0.03)   # the answer is still right

    def test_runs_never_get_shorter_than_the_minimum(self):
        world = FakeWorld(blank_after=set(range(1, 100)))
        with self.assertRaises(RuntimeError):
            self.calibrator(world).straight(seconds=0.5)
        self.assertTrue(all(m[2] >= calibrate.MIN_RUN_S - 1e-9 for m in world.moves))

    def test_a_shorter_run_can_be_asked_for_and_gives_the_same_answer(self):
        world = FakeWorld()
        out = self.calibrator(world).straight(seconds=0.6, reverse=False)
        self.assertTrue(all(m[2] == 0.6 for m in world.moves))
        self.assertAlmostEqual(out["right_trim"], -world.DRIFT / world.SLOPE, delta=0.03)

    # ---- backing up ----
    def test_the_backward_drift_is_measured_and_gets_its_own_trim(self):
        world = FakeWorld(back_drift=-2.5)                            # backing up he veers right
        out = self.calibrator(world).straight()
        self.assertAlmostEqual(out["right_trim"], -world.DRIFT / world.SLOPE, delta=0.02)          # forward as before
        self.assertAlmostEqual(out["back_right_trim"], world.cfg.back_right_trim + (-2.5) / world.SLOPE, delta=0.02)
        self.assertAlmostEqual(out["back_drift_before"], -2.5, delta=0.3)
        self.assertEqual(out["back_left_trim"], 0.0)
        self.assertNotIn("back_error", out)
        self.assertEqual((world.cfg.back_left_trim, world.cfg.back_right_trim), (0.0, 0.0))        # nothing left behind by the test

    def test_only_the_backing_up_part_can_be_run_and_leaves_the_forward_trims_alone(self):
        world = FakeWorld(back_drift=-2.5)
        world.cfg.right_trim = 0.05                                   # a forward trim from an earlier run
        out = self.calibrator(world).straight(forward=False)
        self.assertAlmostEqual(out["back_right_trim"], -2.5 / world.SLOPE, delta=0.02)
        self.assertEqual(out["right_trim"], 0.05)                      # reported as it was
        self.assertNotIn("drift_before", out)                          # (the forward part did not run)
        self.assertEqual(len(world.moves), 4)                          # just the two backing-up runs

    def test_only_the_backing_up_part_reports_its_own_failure_instead_of_hiding_it(self):
        world = FakeWorld(blank_after=set(range(1, 999)), back_drift=-2.5)
        with self.assertRaises(RuntimeError) as cm:
            self.calibrator(world).straight(forward=False)
        self.assertIn("backing up", str(cm.exception))

    def test_doing_neither_part_is_refused(self):
        with self.assertRaises(RuntimeError):
            self.calibrator(FakeWorld()).straight(forward=False, reverse=False)

    def test_reverse_can_be_skipped(self):
        world = FakeWorld(back_drift=-2.5)
        out = self.calibrator(world).straight(reverse=False)
        self.assertNotIn("back_right_trim", out)
        self.assertEqual(len(world.moves), 4)                          # just the forward measurement and its probe

    def test_each_backing_up_run_drives_out_backward_and_returns_forward(self):
        world = FakeWorld(back_drift=-2.5)
        self.calibrator(world).straight()
        back_runs = world.moves[4:]
        self.assertEqual([m[0] < 0 for m in back_runs], [True, False, True, False])
        self.assertEqual({m[2] for m in back_runs}, {1.2})

    def test_if_only_backing_up_cannot_be_measured_the_forward_answer_is_kept(self):
        # grabs: 1 opening check, then 5 per run: the two forward runs use 2-11; everything after is blank
        world = FakeWorld(blank_after=set(range(12, 999)), back_drift=-2.5)
        out = self.calibrator(world).straight()
        self.assertAlmostEqual(out["right_trim"], -world.DRIFT / world.SLOPE, delta=0.02)
        self.assertIn("back_error", out)
        self.assertIn("too plain", out["back_error"])
        self.assertEqual(out["back_right_trim"], 0.0)                  # unchanged
        self.assertNotIn("back_drift_before", out)

    def test_a_reverse_probe_that_changes_nothing_is_reported_not_trusted(self):
        world = FakeWorld()                                            # backing up has no trim effect in this world
        out = self.calibrator(world).straight()
        self.assertIn("by too little", out["back_error"])
        self.assertEqual(out["back_right_trim"], 0.0)

    def test_the_emergency_stop_during_backing_up_ends_everything(self):
        world = FakeWorld(back_drift=-2.5)
        original = world.move

        def move(left, right, seconds):
            ran = original(left, right, seconds)
            if len(world.moves) == 5:
                world.estop.set()
            return ran
        world.move = move
        with self.assertRaises(RuntimeError) as cm:
            self.calibrator(world).straight()
        self.assertIn("calibration stopped", str(cm.exception))        # not swallowed as a "backing up failed"

    def test_the_pictures_of_a_failed_run_are_saved_so_you_can_see_them(self):
        import tempfile
        world = FakeWorld(blank_after=set(range(1, 100)))
        with tempfile.TemporaryDirectory() as d:
            cal = calibrate.Calibrator(world, world, None, FOV, say=self.said.append if hasattr(self, "said") else print,
                                       sleep=lambda s: None, save_failed=d)
            with self.assertRaises(RuntimeError):
                cal.straight()
            files = sorted(p.name for p in Path(d).iterdir())
            self.assertEqual(files, ["calib-failed-after.jpg", "calib-failed-before.jpg"])     # only the latest pair is kept
            self.assertIsNotNone(cv2.imread(str(Path(d) / "calib-failed-after.jpg")))

    def test_a_good_run_saves_nothing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            world = FakeWorld()
            calibrate.Calibrator(world, world, None, FOV, say=lambda m: None, sleep=lambda s: None, save_failed=d).straight(reverse=False)
            self.assertEqual(list(Path(d).iterdir()), [])

    def test_being_stopped_early_is_reported_as_that_and_not_retried(self):
        world = FakeWorld()
        world.move = lambda l, r, s: (world.moves.append((l, r, s)), 0.1)[1]
        with self.assertRaises(RuntimeError) as cm:
            self.calibrator(world).straight()
        self.assertIn("stopped early", str(cm.exception))

    def test_the_emergency_stop_ends_it(self):
        world = FakeWorld()
        world.estop.set()
        with self.assertRaises(RuntimeError) as cm:
            self.calibrator(world).straight()
        self.assertIn("calibration stopped", str(cm.exception))
        self.assertEqual(world.moves, [])


if __name__ == "__main__":
    unittest.main()
