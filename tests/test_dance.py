import os
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import dance  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += max(s, 0.0005)


class FakeDrive:
    """Records where the wheels would have taken him: forward distance and rotation are the sums of speed x time."""

    def __init__(self, clock, refuse_forward=False):
        self.clock = clock
        self.estop = threading.Event()
        self.refuse_forward = refuse_forward
        self.starts = []                 # (left, right, requested seconds)
        self.stops = 0
        self.segments = []               # (t0, t1, left, right) of the wheels really running
        self._cur = None                 # (t0, left, right, deadline)

    def _close(self, now):
        if self._cur:
            t0, l, r, deadline = self._cur
            self.segments.append((t0, min(now, deadline), l, r))
            self._cur = None

    def start(self, left, right, seconds):
        now = self.clock.now()
        self._close(now)
        self.starts.append((left, right, seconds))
        if self.refuse_forward and left + right > 0.05:
            return False
        self._cur = (now, left, right, now + seconds)
        return True

    def stop(self):
        self.stops += 1
        self._close(self.clock.now())

    def net(self):
        forward = sum((t1 - t0) * (l + r) / 2 for t0, t1, l, r in self.segments)
        turn = sum((t1 - t0) * (r - l) / 2 for t0, t1, l, r in self.segments)
        travel = sum((t1 - t0) * (abs(l) + abs(r)) / 2 for t0, t1, l, r in self.segments)
        return forward, turn, travel


class Dancing(unittest.TestCase):
    def make(self, **kw):
        self.clock = Clock()
        self.drive = FakeDrive(self.clock, refuse_forward=kw.pop("refuse_forward", False))
        self.heard = []
        self.cfg = config.DanceConfig(**kw)
        d = dance.Dancer(self.cfg, self.drive, sound=self.heard.append, clock=self.clock.now, sleep=self.clock.sleep)
        d.name, d.active = "party", True
        return d

    def go(self, d, name="party", seconds=60.0, allowed=lambda: True):
        d._stop.clear()
        d._run(name, seconds, allowed)

    # ---- staying in one spot ----
    def test_every_dance_ends_up_where_it_started(self):
        for name in dance.NAMES:
            d = self.make()
            self.go(d, name, 45.0)
            forward, turn, travel = self.drive.net()
            self.assertGreater(travel, 1.0, f"{name} should actually move")
            self.assertLess(abs(forward), 0.02 * travel, f"{name} drifted forward or back: {forward:.3f} of {travel:.2f}")
            self.assertLess(abs(turn), 0.02 * travel, f"{name} ended up turned: {turn:.3f} of {travel:.2f}")

    def test_a_short_time_limit_never_cuts_a_step_in_half(self):
        for seconds in (3.0, 4.2, 7.7, 10.0):
            d = self.make()
            self.go(d, "party", seconds)
            forward, turn, travel = self.drive.net()
            self.assertLess(abs(forward), 0.02 * max(travel, 0.1), seconds)
            self.assertLess(abs(turn), 0.02 * max(travel, 0.1), seconds)
            self.assertLess(self.clock.t, seconds + 4.0, "it must not run on for long after the time is up")
            self.assertIn("time was up", d.result)

    def test_it_runs_for_about_the_time_asked(self):
        d = self.make()
        self.go(d, "wiggle", 20.0)
        self.assertGreater(self.clock.t, 19.0)
        self.assertLess(self.clock.t, 24.0)

    def test_he_never_goes_faster_than_the_dance_speed(self):
        d = self.make(speed=0.3)
        self.go(d, "party", 30.0)
        for left, right, _ in self.drive.starts:
            self.assertLessEqual(max(abs(left), abs(right)), 0.3 + 1e-9)

    def test_every_wheel_command_is_short_so_he_stops_by_himself_if_it_dies(self):
        d = self.make()
        self.go(d, "party", 30.0)
        self.assertTrue(self.drive.starts)
        self.assertLessEqual(max(s for _, _, s in self.drive.starts), 1.5 * 1.0 + 1e-9)

    # ---- what ends it ----
    def test_stop_ends_it_at_once_and_stops_the_wheels(self):
        d = self.make()
        orig = self.clock.sleep

        def sleeping(s):
            orig(s)
            if self.clock.t > 5.0:
                d.stop("told to stop")
        d._sleep = sleeping
        self.go(d, "party", 120.0)
        self.assertLess(self.clock.t, 5.5)
        self.assertIn("told to stop", d.result)
        self.assertFalse(d.active)
        self.assertIsNone(self.drive._cur)                          # the wheels are not left running

    def test_the_emergency_stop_ends_it(self):
        d = self.make()
        orig = self.clock.sleep

        def sleeping(s):
            orig(s)
            if self.clock.t > 3.0:
                self.drive.estop.set()
        d._sleep = sleeping
        self.go(d, "party", 120.0)
        self.assertIn("emergency stop", d.result)
        self.assertLess(self.clock.t, 3.5)

    def test_not_allowed_ends_it(self):
        d = self.make()
        self.go(d, "party", 120.0, allowed=lambda: self.clock.t < 4.0)
        self.assertIn("paused", d.result)
        self.assertLess(self.clock.t, 4.5)

    def test_a_crash_stops_the_wheels(self):
        d = self.make()
        d.drive.start = lambda *a: 1 / 0
        self.go(d, "party", 30.0)
        self.assertIn("error", d.result)
        self.assertGreaterEqual(self.drive.stops, 1)

    # ---- the distance sensor ----
    def test_a_refused_forward_step_skips_the_whole_out_and_back(self):
        d = self.make(refuse_forward=True)
        self.go(d, "steps", 30.0)
        backward = [s for s in self.drive.starts if s[0] + s[1] < -0.05]
        self.assertEqual(backward, [], "no way-back leg for a step that never went out")
        self.assertIn("skipped", d.result)
        forward, turn, travel = self.drive.net()
        self.assertEqual((round(forward, 6), round(travel, 6)), (0.0, 0.0))

    def test_spins_still_happen_when_forward_steps_are_refused(self):
        d = self.make(refuse_forward=True)
        self.go(d, "party", 30.0)
        forward, turn, travel = self.drive.net()
        self.assertGreater(travel, 0.5)
        self.assertLess(abs(forward), 0.02 * travel)

    # ---- sounds ----
    def test_sounds_play_along(self):
        d = self.make()
        self.go(d, "party", 30.0)
        self.assertIn("startup", self.heard)
        self.assertTrue(set(self.heard) <= {"startup", "chirp", "beep", "happy"})

    def test_sounds_can_be_switched_off_and_a_broken_speaker_does_not_stop_the_dance(self):
        d = self.make(sounds=False)
        self.go(d, "party", 30.0)
        self.assertEqual(self.heard, [])
        d = self.make()
        d.sound = lambda n: 1 / 0
        self.go(d, "wiggle", 10.0)
        self.assertIn("time was up", d.result)

    # ---- starting ----
    def test_start_checks(self):
        d = self.make()
        d.active = False
        self.assertIn("unknown dance", d.start("breakdance"))
        self.drive.estop.set()
        self.assertIn("emergency stop", d.start("party"))
        self.drive.estop.clear()
        d.active = True
        self.assertIn("already dancing", d.start("party"))

    def test_the_time_asked_for_is_kept_within_limits(self):
        d = self.make(max_seconds=100.0, default_seconds=30.0)
        d.active = False
        seen = []
        d._run = lambda name, seconds, allowed: seen.append(seconds)
        for ask in (None, 1.0, 500.0, 45.0):
            d.active = False
            d.start("wiggle", ask)
            d._thread.join(2)
        self.assertEqual(seen, [30.0, 3.0, 100.0, 45.0])


class OnTheController(unittest.TestCase):
    def setUp(self):
        import bob
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        cfg = config.Config()
        cfg.stream.enabled = False
        self.ctrl = bob.Controller(cfg, sim=True, paused=True)
        self.addCleanup(self.ctrl.shutdown)
        self.d = self.ctrl.dancer
        self.addCleanup(self.d.stop)

    def wait_until(self, cond, t=3.0):
        end = time.time() + t
        while time.time() < end and not cond():
            time.sleep(0.01)
        return cond()

    def test_it_starts_pauses_the_ai_and_stops_on_command(self):
        self.ctrl.controls.auto = True
        out = self.ctrl.handle("/dance wiggle 20")
        self.assertIn("dancing the wiggle for up to 20s", out)
        self.assertIn("AI is paused", out)
        self.assertFalse(self.ctrl.controls.auto)
        self.assertTrue(self.d.active)
        self.assertIn("DANCING", self.ctrl.status_line())
        self.assertEqual(self.ctrl.handle("/dance off"), "stopping")
        self.assertTrue(self.wait_until(lambda: not self.d.active))
        self.assertIn("ended: stopped by the operator", self.d.result)

    def test_the_default_is_the_party_dance(self):
        self.assertIn("party", self.ctrl.handle("/dance"))
        self.ctrl.handle("/dance off")

    def test_usage_and_refusals(self):
        self.assertIn("usage", self.ctrl.handle("/dance breakdance"))
        self.assertIn("usage", self.ctrl.handle("/dance wiggle fast"))
        self.ctrl.controls.motion_enabled = False
        self.assertIn("movement is disabled", self.ctrl.handle("/dance"))
        self.ctrl.controls.motion_enabled = True
        self.ctrl.follower.active = True
        self.assertIn("following something", self.ctrl.handle("/dance"))
        self.ctrl.follower.active = False
        self.assertFalse(self.d.active)

    def test_a_refused_start_leaves_the_ai_as_it_was(self):
        self.ctrl.controls.auto = True
        self.ctrl.drive.estop.set()
        self.assertIn("can't dance", self.ctrl.handle("/dance"))
        self.assertTrue(self.ctrl.controls.auto)

    def test_it_cannot_run_together_with_colour_following(self):
        self.ctrl.handle("/dance wiggle 30")
        self.assertIn("dancing", self.ctrl.handle("/color follow red").lower())
        self.ctrl.handle("/dance off")
        self.wait_until(lambda: not self.d.active)
        self.ctrl.camera.grab_bgr = lambda: object()
        f = self.ctrl.color_follower
        f.active = True
        self.assertIn("following something", self.ctrl.handle("/dance"))
        f.active = False

    def test_every_override_ends_it(self):
        for end in (lambda: self.ctrl.handle("/estop"), lambda: self.ctrl.handle("/pause"),
                    lambda: self.ctrl.handle("/motion off"), lambda: self.ctrl.handle("/resume"),
                    lambda: self.ctrl.handle("/drive"), lambda: self.ctrl.manual(0.5, 0.5, 0.4),
                    lambda: self.ctrl.voice_command("stop")):
            self.ctrl.drive.estop.clear()
            self.ctrl.controls.motion_enabled = True
            self.ctrl.controls.auto = False
            self.ctrl.drive_mode = False
            self.assertIn("dancing", self.ctrl.handle("/dance spin 60"))
            self.assertTrue(self.wait_until(lambda: self.d.active))
            end()
            self.assertTrue(self.wait_until(lambda: not self.d.active), f"still dancing after {end}")

    def test_it_can_be_turned_off_in_the_config(self):
        import bob
        cfg = config.Config()
        cfg.stream.enabled = False
        cfg.dance.enabled = False
        c = bob.Controller(cfg, sim=True, paused=True)
        self.addCleanup(c.shutdown)
        self.assertIsNone(c.dancer)
        self.assertIn("dancing is off", c.handle("/dance"))

    def test_claude_has_no_tool_to_start_it_and_help_mentions_it(self):
        import brain
        names = {t["name"] for t in brain.build_tools(3.0, colors=True, mecanum=True)}
        self.assertFalse({n for n in names if "dance" in n})
        self.assertIn("/dance", self.ctrl.handle("/help"))


class TheSettings(unittest.TestCase):
    def test_defaults_and_loading(self):
        import tempfile
        c = config.DanceConfig()
        self.assertEqual((c.enabled, c.speed, c.default_seconds, c.max_seconds, c.sounds), (True, 0.5, 30.0, 300.0, True))
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "config.toml"
            p.write_text("[dance]\nspeed = 0.3\nsounds = false\n")
            cfg = config.load(p)
            self.assertEqual((cfg.dance.speed, cfg.dance.sounds), (0.3, False))
            p.write_text("[dance]\nspeeed = 0.3\n")
            with self.assertRaises(ValueError):
                config.load(p)


if __name__ == "__main__":
    unittest.main()
