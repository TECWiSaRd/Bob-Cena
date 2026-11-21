import os
import sys
import threading
import time
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

try:
    import cv2  # noqa: F401
    import numpy as np
except ImportError:                                  # a Mac venv without OpenCV: these tests are skipped
    np = None

import colors  # noqa: E402

RED = (220, 20, 20)


def frame(x0=None, x1=None, rgb=RED, y0=40, y1=80):
    img = np.zeros((120, 160, 3), np.uint8)
    img[:] = 128
    if x0 is not None:
        img[y0:y1, x0:x1] = rgb[::-1]
    return img


class Clock:
    """Simulated time: sleeping just moves the clock, so a long run takes no time."""

    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += max(s, 0.001)


class FakeCamera:
    def __init__(self, frames):
        self.frames = frames                         # a function (step number) -> picture or None
        self.n = 0

    def grab_bgr(self):
        self.n += 1
        return self.frames(self.n)


class FakeDrive:
    def __init__(self, refuse_forward=False):
        self.estop = threading.Event()
        self.calls = []                              # ("start", left, right) or ("stop",)
        self.refuse_forward = refuse_forward

    def start(self, left, right, seconds, *a):
        self.calls.append(("start", round(left, 3), round(right, 3)))
        if self.refuse_forward and left + right > 0.05:
            return False
        return True

    def stop(self):
        self.calls.append(("stop",))

    def moves(self):
        return [c for c in self.calls if c[0] == "start"]


@unittest.skipIf(np is None, "needs OpenCV and numpy")
class Following(unittest.TestCase):
    def make(self, frames, drive=None, **cfg):
        self.clock = Clock()
        self.drive = drive or FakeDrive()
        self.cam = FakeCamera(frames)
        self.cfg = config.ColorsConfig(**cfg)
        f = colors.ColorFollower(self.cfg, colors.ColorFinder(self.cfg, 62.0), self.cam, self.drive,
                                 clock=self.clock.now, sleep=self.clock.sleep)
        f.color, f.active = "red", True
        return f

    def run_until(self, f, steps, allowed=lambda: True):
        """Run the loop until the camera has been asked `steps` times, then stop it the way an operator would."""
        orig = self.cam.frames

        def counting(n):
            if n >= steps:
                f.stop("test over")
            return orig(n)
        self.cam.frames = counting
        f._run(allowed)

    # ---- steering ----
    def test_a_colour_on_the_right_turns_him_right(self):
        f = self.make(lambda n: frame(120, 150))
        self.run_until(f, 5)
        left, right = self.drive.moves()[0][1:]
        self.assertGreater(left, 0)
        self.assertLess(right, left)                 # the left wheel faster: turning right

    def test_a_colour_on_the_left_turns_him_left(self):
        f = self.make(lambda n: frame(10, 40))
        self.run_until(f, 5)
        left, right = self.drive.moves()[0][1:]
        self.assertGreater(right, left)

    def test_a_small_colour_straight_ahead_makes_him_drive_forward(self):
        f = self.make(lambda n: frame(72, 88, y0=50, y1=70))
        self.run_until(f, 5)
        left, right = self.drive.moves()[0][1:]
        self.assertGreater(left, 0.05)
        self.assertAlmostEqual(left, right, places=3)

    def test_he_stops_coming_closer_once_it_fills_enough_of_the_picture(self):
        f = self.make(lambda n: frame(40, 120, y0=20, y1=100))      # a big centred patch (about 33%)
        self.run_until(f, 6)
        self.assertEqual(self.drive.moves(), [])                    # no forward move at all
        self.assertEqual(self.drive.calls[-1], ("stop",))

    def test_he_never_goes_faster_than_follow_speed(self):
        f = self.make(lambda n: frame(110, 156, y0=55, y1=65), follow_speed=0.3)
        self.run_until(f, 8)
        for _, left, right in self.drive.moves():
            self.assertLessEqual(max(abs(left), abs(right)), 0.3 + 1e-9)

    def test_he_does_not_drive_ahead_while_facing_well_away(self):
        f = self.make(lambda n: frame(2, 20, y0=45, y1=75))          # far left edge, small (about 3%)
        self.run_until(f, 5)
        left, right = self.drive.moves()[0][1:]
        self.assertLess(left + right, 0.05)                          # he spins toward it instead

    # ---- until stopped ----
    def test_it_keeps_going_for_a_long_time_without_any_time_limit(self):
        f = self.make(lambda n: frame(72, 88, y0=50, y1=70))
        self.run_until(f, 4000)                                     # about 8 minutes of simulated time
        self.assertGreater(self.clock.t, 450)
        self.assertIn("test over", f.result)                         # it ended only because it was told to
        self.assertFalse(f.active)

    def spins(self, calls):
        return [c for c in calls if c[0] == "start"]

    def test_losing_the_colour_makes_him_turn_toward_where_it_went_until_it_is_found(self):
        seen_until = 20
        f = self.make(lambda n: frame(120, 150) if n <= seen_until else frame())
        self.run_until(f, 600)                                      # 75 s with nothing in view
        after = self.drive.calls[seen_until:]
        spins = self.spins(after)
        self.assertTrue(all(c[1] > 0 > c[2] for c in spins), "turning toward the right, where it was last seen")
        late = self.spins(self.drive.calls[-24:])
        self.assertTrue(late, "and he is still looking a minute later: no time limit")
        self.assertIn("test over", f.result)                         # it ended only because it was told to

    def test_the_search_turns_in_bursts_with_pauses_so_the_picture_is_sharp(self):
        f = self.make(lambda n: frame(120, 150) if n <= 5 else frame())
        self.run_until(f, 200)
        after = self.drive.calls[8:]
        turning = len(self.spins(after))
        holding = len([c for c in after if c[0] == "stop"])
        self.assertGreater(turning, 10)
        self.assertGreater(holding, 10)                              # about half the time he is still
        self.assertLess(abs(turning - holding), max(turning, holding) * 0.5)

    def test_a_colour_he_has_not_seen_yet_makes_him_turn_right_at_once_and_then_follow_it_when_it_appears(self):
        f = self.make(lambda n: frame() if n <= 30 else frame(10, 40))   # appears on the left after a while
        self.run_until(f, 60)
        first = self.spins(self.drive.calls)[0]
        self.assertTrue(first[1] > 0 > first[2], "turns right to begin with")
        last = self.spins(self.drive.calls)[-1]
        self.assertGreater(last[2], last[1])                         # then turns left toward it

    def test_a_missed_picture_does_not_start_a_search(self):
        f = self.make(lambda n: frame() if n == 10 else frame(72, 88, y0=50, y1=70))
        self.run_until(f, 11)
        steps_10 = self.drive.calls[9:11]
        self.assertFalse([c for c in steps_10 if c[0] == "start" and c[1] > 0 > c[2]], "no spin for a single missed picture")

    def test_a_search_limit_makes_him_give_up_turning_but_keep_watching(self):
        f = self.make(lambda n: frame(120, 150) if n <= 5 else (frame(120, 150) if n > 300 else frame()), follow_search_s=6.0)
        self.run_until(f, 330)
        mid = self.spins(self.drive.calls[8:300])
        self.assertLessEqual(len(mid) * colors.ColorFollower.period, 6.0)          # turned for about 6 s, no more
        self.assertTrue(self.spins(self.drive.calls[-6:]))                         # and follows again when it returns

    def test_it_picks_up_again_when_the_colour_returns(self):
        f = self.make(lambda n: frame(120, 150) if (n < 10 or n > 100) else frame())
        self.run_until(f, 130)
        late = [c for c in self.drive.calls[-8:] if c[0] == "start"]
        self.assertTrue(late, "he should be steering again once it is back")
        self.assertTrue(all(c[1] > c[2] for c in late), "toward the right, where it came back")

    # ---- things that end it ----
    def test_the_emergency_stop_ends_it_and_stops_the_wheels(self):
        f = self.make(lambda n: frame(72, 88, y0=50, y1=70))
        self.cam.frames = lambda n: (self.drive.estop.set() if n == 5 else None) or frame(72, 88, y0=50, y1=70)
        f._run(lambda: True)
        self.assertIn("emergency stop", f.result)
        self.assertEqual(self.drive.calls[-1], ("stop",))

    def test_not_allowed_ends_it(self):
        f = self.make(lambda n: frame(72, 88, y0=50, y1=70))
        steps = {"n": 0}

        def allowed():
            steps["n"] += 1
            return steps["n"] < 6
        f._run(allowed)
        self.assertIn("paused", f.result)
        self.assertEqual(self.drive.calls[-1], ("stop",))

    def test_a_lost_camera_ends_it_after_a_couple_of_seconds(self):
        f = self.make(lambda n: frame(72, 88) if n < 5 else None)
        f._run(lambda: True)
        self.assertIn("camera", f.result)
        self.assertEqual(self.drive.calls[-1], ("stop",))
        self.assertLess(self.clock.t, 6)

    def test_a_crash_stops_the_wheels(self):
        f = self.make(lambda n: frame(72, 88))
        f.finder.analyze = lambda *a, **k: 1 / 0
        f._run(lambda: True)
        self.assertIn("error", f.result)
        self.assertEqual(self.drive.calls[-1], ("stop",))

    def test_the_distance_sensor_refusing_forward_leaves_him_turning_only_and_not_asking_every_step(self):
        f = self.make(lambda n: frame(110, 140, y0=55, y1=65), drive=FakeDrive(refuse_forward=True))
        self.run_until(f, 40)
        forward = [c for c in self.drive.moves() if c[1] + c[2] > 0.05]
        self.assertLessEqual(len(forward), 8)                        # about once a second, not 40 times
        self.assertTrue(any(c[1] > 0 > c[2] for c in self.drive.moves()))   # but he still turns toward it

    # ---- how close he gets ----
    def test_a_distance_setting_makes_him_stop_coming_closer_at_that_distance(self):
        ranger = types.SimpleNamespace(distance_cm=120.0)
        f = self.make(lambda n: frame(72, 88, y0=50, y1=70), follow_distance_cm=40)
        f.ranger = ranger
        orig = self.cam.frames

        def closer(n):
            ranger.distance_cm = 120.0 if n < 10 else 35.0           # he rolls up to 35 cm
            return orig(n)
        self.cam.frames = closer
        self.run_until(f, 25)
        early = [c for c in self.drive.calls[:8] if c[0] == "start"]
        self.assertTrue(early and early[0][1] > 0.05 and early[0][2] > 0.05, "far away: he comes forward")
        late = [c for c in self.drive.calls[-6:] if c[0] == "start"]
        self.assertFalse([c for c in late if c[1] + c[2] > 0.05], "near enough: no more forward")

    def test_the_distance_setting_does_nothing_when_it_is_zero_or_there_is_no_sensor(self):
        f = self.make(lambda n: frame(72, 88, y0=50, y1=70), follow_distance_cm=0)
        f.ranger = types.SimpleNamespace(distance_cm=5.0)
        self.run_until(f, 6)
        self.assertTrue([c for c in self.drive.moves() if c[1] + c[2] > 0.05])
        g = self.make(lambda n: frame(72, 88, y0=50, y1=70), follow_distance_cm=40)
        self.run_until(g, 6)                                         # no sensor at all
        self.assertTrue([c for c in self.drive.moves() if c[1] + c[2] > 0.05])

    def test_a_sensor_with_no_reading_does_not_stop_him(self):
        f = self.make(lambda n: frame(72, 88, y0=50, y1=70), follow_distance_cm=40)
        f.ranger = types.SimpleNamespace(distance_cm=None)
        self.run_until(f, 6)
        self.assertTrue([c for c in self.drive.moves() if c[1] + c[2] > 0.05])

    def test_the_new_settings_can_be_changed_with_set_and_stay_in_range(self):
        for key, ok, bad in (("follow_distance_cm", "40", "400"), ("follow_percent", "25", "0"),
                             ("follow_speed", "0.3", "2"), ("follow_search_s", "30", "-1")):
            self.assertIsNotNone(config.parse_setting("colors", key, ok))
            with self.assertRaises(ValueError, msg=key):
                config.parse_setting("colors", key, bad)

    # ---- starting ----
    def test_start_refuses_in_the_right_cases(self):
        f = self.make(lambda n: frame(72, 88))
        f.active = False
        self.assertIn("unknown colour", f.start("plaid"))
        self.drive.estop.set()
        self.assertIn("emergency stop", f.start("red"))
        self.drive.estop.clear()
        self.cam.frames = lambda n: None
        self.assertIn("no camera picture", f.start("red"))
        self.cam.frames = lambda n: frame(72, 88)
        f.active = True
        f.color = "blue"
        self.assertIn("already following blue", f.start("red"))


@unittest.skipIf(np is None, "needs OpenCV and numpy")
class OnTheController(unittest.TestCase):
    def setUp(self):
        import bob
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        cfg = config.Config()
        cfg.stream.enabled = False
        self.ctrl = bob.Controller(cfg, sim=True, paused=True)
        self.addCleanup(self.ctrl.shutdown)
        self.ctrl.camera.grab_bgr = lambda: frame(72, 88, y0=50, y1=70)
        self.ctrl.camera.enabled = True
        self.f = self.ctrl.color_follower
        self.f.period = 0.01
        self.addCleanup(self.f.stop)

    def wait_until(self, cond, t=2.0):
        end = time.time() + t
        while time.time() < end and not cond():
            time.sleep(0.01)
        return cond()

    def test_it_starts_pauses_the_ai_and_stops_on_command(self):
        self.ctrl.controls.auto = True
        out = self.ctrl.handle("/color follow red")
        self.assertIn("following red until you stop him", out)
        self.assertIn("AI is paused", out)
        self.assertFalse(self.ctrl.controls.auto)
        self.assertTrue(self.f.active)
        self.assertIn("FOLLOWING RED", self.ctrl.status_line())
        self.assertEqual(self.ctrl.handle("/color follow off"), "stopping")
        self.assertTrue(self.wait_until(lambda: not self.f.active))
        self.assertIn("ended: stopped by the operator", self.f.result)

    def test_unknown_colour_and_missing_word(self):
        self.assertIn("usage", self.ctrl.handle("/color follow plaid"))
        self.assertIn("usage", self.ctrl.handle("/color follow"))
        self.assertFalse(self.f.active)

    def test_it_refuses_when_movement_is_off_or_a_face_is_being_followed(self):
        self.ctrl.controls.motion_enabled = False
        self.assertIn("movement is disabled", self.ctrl.handle("/color follow red"))
        self.ctrl.controls.motion_enabled = True
        self.ctrl.follower.active = True
        self.assertIn("following a face", self.ctrl.handle("/color follow red"))
        self.ctrl.follower.active = False
        self.assertFalse(self.f.active)

    def test_a_refused_start_leaves_the_ai_as_it_was(self):
        self.ctrl.controls.auto = True
        self.ctrl.camera.grab_bgr = lambda: None
        self.assertIn("can't follow red", self.ctrl.handle("/color follow red"))
        self.assertTrue(self.ctrl.controls.auto)

    def test_every_override_ends_it(self):
        for end in (lambda: self.ctrl.handle("/estop"), lambda: self.ctrl.handle("/pause"),
                    lambda: self.ctrl.handle("/motion off"), lambda: self.ctrl.handle("/resume"),
                    lambda: self.ctrl.handle("/drive"), lambda: self.ctrl.manual(0.5, 0.5, 0.4),
                    lambda: self.ctrl.voice_command("stop")):
            self.ctrl.drive.estop.clear()
            self.ctrl.controls.motion_enabled = True
            self.ctrl.controls.auto = False
            self.ctrl.drive_mode = False
            self.assertIn("following", self.ctrl.handle("/color follow red"))
            self.assertTrue(self.wait_until(lambda: self.f.active))
            end()
            self.assertTrue(self.wait_until(lambda: not self.f.active), f"still following after {end}")

    def test_the_emergency_stop_works_while_following(self):
        self.ctrl.handle("/color follow red")
        self.ctrl.handle("/estop")
        self.assertTrue(self.wait_until(lambda: not self.f.active))
        self.assertTrue(self.ctrl.drive.estop.is_set())
        self.assertIn("E-stop", self.ctrl.handle("/fwd 1"))
        self.assertIn("emergency stop is on", self.ctrl.handle("/color follow red"))

    def test_claude_has_no_tool_to_start_it(self):
        import brain
        names = {t["name"] for t in brain.build_tools(3.0, colors=True)}
        self.assertFalse({n for n in names if "follow_color" in n or "color_follow" in n or "follow_colour" in n})
        self.assertIn("see_colors", names)                           # he can still look
        self.assertTrue(self.ctrl.color_follower is not None)

    def test_help_mentions_it(self):
        self.assertIn("/color follow", self.ctrl.handle("/help"))


if __name__ == "__main__":
    unittest.main()
