import os
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from sleepmode import SleepMode  # noqa: E402


class Clock:
    t = 100.0

    def __call__(self):
        return self.t


class ModeTests(unittest.TestCase):
    def setUp(self):
        self.clock, self.hour = Clock(), 14
        self.mode = SleepMode(config.SleepConfig(enabled=True, start="23:00", end="07:00", wake_for_s=120.0),
                              now=lambda: datetime(2026, 10, 22, self.hour, 30), clock=self.clock)

    def test_the_schedule_wraps_past_midnight(self):
        for hour, asleep in ((14, False), (22, False), (23, True), (3, True), (6, True), (7, False)):
            self.hour = hour
            self.assertEqual(self.mode.asleep(), asleep, hour)

    def test_manual_overrides_the_schedule(self):
        self.mode.set("on")
        self.assertTrue(self.mode.asleep())
        self.hour = 23
        self.mode.set("off")
        self.assertFalse(self.mode.asleep())
        self.mode.set("auto")
        self.assertTrue(self.mode.asleep())

    def test_someone_speaking_wakes_him_for_a_while_then_he_drifts_off(self):
        self.hour = 2
        self.assertTrue(self.mode.asleep())
        self.mode.poke()
        self.assertFalse(self.mode.asleep())
        self.clock.t += 119
        self.assertFalse(self.mode.asleep())
        self.clock.t += 2
        self.assertTrue(self.mode.asleep())

    def test_manual_off_stays_off_whatever_the_time(self):
        self.hour = 2
        self.mode.set("off")
        self.clock.t += 10_000
        self.assertFalse(self.mode.asleep())

    def test_without_a_schedule_only_the_command_makes_him_sleep(self):
        mode = SleepMode(config.SleepConfig(enabled=False), now=lambda: datetime(2026, 10, 22, 3, 0), clock=self.clock)
        self.assertFalse(mode.asleep())
        mode.set("on")
        self.assertTrue(mode.asleep())

    def test_a_bad_time_is_reported_not_crashed_on(self):
        mode = SleepMode(config.SleepConfig(enabled=True, start="25:99"), clock=self.clock)
        self.assertIn("isn't a time", mode.describe())
        self.assertFalse(mode.asleep())

    def test_usage_message_for_nonsense(self):
        self.assertIn("usage", self.mode.set("maybe"))


class ThroughTheRobot(unittest.TestCase):
    def setUp(self):
        import bob
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        cfg = config.Config()
        cfg.stream.enabled = False
        self.ctrl = bob.Controller(cfg, sim=True, paused=False)
        self.addCleanup(self.ctrl.shutdown)

    def test_asleep_the_ai_cannot_drive_but_the_operator_can(self):
        self.ctrl.handle("/sleep on")
        self.assertIn("SLEEPING", self.ctrl.status_line())
        self.assertIn("sleep time", self.ctrl.brain._motion_block())
        self.assertIn("sleep time", self.ctrl.brain._run_tool(type("B", (), {"name": "drive", "type": "tool_use", "input": {"direction": "forward", "speed": 0.5, "seconds": 1}, "id": "x"})())["content"])
        self.assertIn("manual move", self.ctrl.handle("/move 0.3 0.3 0.2"))          # the operator is not blocked
        self.ctrl.handle("/sleep off")
        self.assertIsNone(self.ctrl.brain._motion_block())

    def test_a_message_wakes_him_and_claude_is_told_to_be_quiet_when_asleep(self):
        self.ctrl.handle("/sleep on")
        self.assertIn("SLEEP MODE", self.ctrl.brain._status([], False))
        self.ctrl.controls.post("hello")
        self.assertFalse(self.ctrl.controls.asleep())
        self.assertNotIn("SLEEP MODE", self.ctrl.brain._status([], False))

    def test_the_dashboard_reports_sleeping(self):
        import stream
        srv = stream.StreamServer(config.StreamConfig(), self.ctrl.camera, self.ctrl.access)
        srv.attach(self.ctrl, None)
        self.ctrl.handle("/sleep on")
        self.assertEqual(srv.status()["mode"], "SLEEPING")


if __name__ == "__main__":
    unittest.main()
