import os
import sys
import unittest
from pathlib import Path

try:
    import numpy as np
except ImportError:                       # the Pi has numpy through OpenCV; a bare test environment may not
    raise unittest.SkipTest("numpy not installed")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from change import ChangeGate, changed_percent, small  # noqa: E402


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


def picture(level=100, patch=None):
    frame = np.full((480, 640, 3), level, dtype="uint8")
    if patch:
        x0, y0, x1, y1, v = patch
        frame[y0:y1, x0:x1] = v
    return frame


class GateTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.cfg = config.BrainConfig(think_when="change", tick_seconds=2.0, idle_max_s=60.0,
                                      change_percent=4.0, change_distance_cm=15.0)
        self.gate = ChangeGate(self.cfg, clock=self.clock)
        self.still = small(picture())

    def look(self, pic=None, dist=None, mail=False, force=False):
        return self.gate.check(self.still if pic is None else pic, dist, mail, force)

    def test_it_thinks_once_at_the_start_then_not_while_nothing_changes(self):
        self.assertTrue(self.look())
        for _ in range(20):
            self.clock.t += 2.5
            self.assertFalse(self.look())
        self.assertEqual(self.gate.skipped, 20)

    def test_a_person_walking_in_triggers_a_thought(self):
        self.look()
        self.clock.t += 3
        person = small(picture(patch=(200, 100, 420, 480, 230)))        # a big bright shape
        self.assertTrue(self.look(person))
        self.assertIn("picture changed", self.gate.reason)

    def test_camera_noise_and_slow_drift_do_not(self):
        self.look()
        rng = np.random.default_rng(1)
        noisy = np.clip(picture().astype(int) + rng.integers(-6, 7, (480, 640, 3)), 0, 255).astype("uint8")
        self.clock.t += 3
        self.assertFalse(self.look(small(noisy)))
        self.clock.t += 3
        self.assertFalse(self.look(small(picture(level=112))))             # auto-exposure creeping by 12 levels

    def test_a_lights_on_or_off_change_does(self):
        self.look()
        self.clock.t += 3
        self.assertTrue(self.look(small(picture(level=20))))

    def test_never_sooner_than_tick_seconds(self):
        self.look()
        self.clock.t += 0.5
        self.assertFalse(self.look(small(picture(level=20))))              # changed, but too soon
        self.clock.t += 2
        self.assertTrue(self.look(small(picture(level=20))))

    def test_messages_wake_him_at_once(self):
        self.look()
        self.clock.t += 0.1
        self.assertTrue(self.look(mail=True))
        self.assertIn("message", self.gate.reason)

    def test_the_distance_sensor_moving_a_lot_does(self):
        self.look(dist=100)
        self.clock.t += 3
        self.assertFalse(self.look(dist=105))
        self.assertTrue(self.look(dist=60))

    def test_a_quiet_room_still_gets_a_routine_look(self):
        self.look()
        self.clock.t += 59
        self.assertFalse(self.look())
        self.clock.t += 2
        self.assertTrue(self.look())
        self.assertIn("routine", self.gate.reason)

    def test_without_a_camera_it_falls_back_to_messages_distance_and_the_heartbeat(self):
        self.gate.check(None, None, False)
        self.clock.t += 5
        self.assertFalse(self.gate.check(None, None, False))
        self.clock.t += 60
        self.assertTrue(self.gate.check(None, None, False))

    def test_the_operators_step_always_goes_ahead(self):
        self.look()
        self.clock.t += 0.1
        self.assertTrue(self.look(force=True))

    def test_a_differently_sized_picture_counts_as_changed(self):
        self.assertEqual(changed_percent(self.still, self.still[:5]), 100.0)


class ThroughTheRobot(unittest.TestCase):
    def setUp(self):
        import bob
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        cfg = config.Config()
        cfg.stream.enabled = False
        self.ctrl = bob.Controller(cfg, sim=True, paused=True)
        self.addCleanup(self.ctrl.shutdown)

    def test_think_command_switches_modes(self):
        self.assertIn("only when something changes", self.ctrl.handle("/think change"))
        self.assertEqual(self.ctrl.cfg.brain.think_when, "change")
        self.assertIn("only when something changes", self.ctrl.handle("/think"))
        self.assertIn("every", self.ctrl.handle("/think always"))
        self.assertEqual(self.ctrl.cfg.brain.think_when, "interval")

    def test_the_brain_uses_the_gate_and_tells_claude_why(self):
        brain = self.ctrl.brain
        brain.cfg.think_when = "change"
        brain.camera = type("C", (), {"enabled": True, "grab_bgr": staticmethod(lambda: picture())})()
        self.assertTrue(brain._something_changed())                      # the first look
        self.assertFalse(brain._something_changed())                     # too soon, and nothing changed
        self.assertIn("because", brain._status([], True))

    def test_bad_value_is_rejected_by_the_config_check(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.toml"
            p.write_text('[brain]\nthink_when = "somtimes"\n')
            with self.assertRaisesRegex(ValueError, "isn't one of"):
                config.load(p)


if __name__ == "__main__":
    unittest.main()
