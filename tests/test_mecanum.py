import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
import hardware  # noqa: E402
from test_four_wheels import FakeDuty, FakePins, fake_make_duty  # noqa: E402
import types  # noqa: E402

# Four wheels, each on its own pins (front left 5/6, front right 16/20, rear left 27/22, rear right 25/4).
OWN_PINS = dict(drive_style="mecanum", dc_wheels=4, left_invert=False, right_invert=False,
                dc_rear_left_pwm=18, dc_rear_left_in1=27, dc_rear_left_in2=22,
                dc_rear_right_pwm=19, dc_rear_right_in1=25, dc_rear_right_in2=4)


class TheMix(unittest.TestCase):
    mix = staticmethod(hardware.Drive.mecanum_mix)

    def test_straight_ahead_and_back_move_every_wheel_together(self):
        self.assertEqual(self.mix(1, 1, 0), (1, 1, 1, 1))
        self.assertEqual(self.mix(-0.5, -0.5, 0), (-0.5, -0.5, -0.5, -0.5))

    def test_a_spin_turns_the_sides_opposite_ways(self):
        self.assertEqual(self.mix(-1, 1, 0), (-1, 1, -1, 1))

    def test_sliding_right_is_the_diagonal_pattern(self):
        self.assertEqual(self.mix(0, 0, 1), (1, -1, -1, 1))
        self.assertEqual(self.mix(0, 0, -1), (-1, 1, 1, -1))

    def test_too_much_is_scaled_down_together_so_the_direction_stays_right(self):
        fl, fr, rl, rr = self.mix(1, 1, 1)           # forward and right at once: raw (2, 0, 0, 2)
        self.assertEqual((fl, fr, rl, rr), (1.0, 0.0, 0.0, 1.0))
        fl, fr, rl, rr = self.mix(0.8, 0.4, 0.8)     # raw (1.6, -0.4, 0, 1.2)
        self.assertAlmostEqual(max(abs(w) for w in (fl, fr, rl, rr)), 1.0)
        self.assertAlmostEqual(fr / fl, -0.4 / 1.6)
        self.assertAlmostEqual(rr / fl, 1.2 / 1.6)

    def test_wild_inputs_are_clamped(self):
        self.assertEqual(self.mix(9, 9, 0), (1, 1, 1, 1))
        self.assertTrue(all(abs(w) <= 1 for w in self.mix(5, -5, 5)))


class FakeGpioCase(unittest.TestCase):
    def setUp(self):
        self.pins = FakePins()
        self._old = sys.modules.get("gpiozero")
        sys.modules["gpiozero"] = self.pins.module()
        self._old_duty = hardware._make_duty
        hardware._make_duty = fake_make_duty
        FakeDuty.made = {}

    def tearDown(self):
        hardware._make_duty = self._old_duty
        if self._old is None:
            sys.modules.pop("gpiozero", None)
        else:
            sys.modules["gpiozero"] = self._old


class TheBoard(FakeGpioCase):
    def test_four_wheels_each_have_their_own_channel(self):
        board = hardware.Tb6612(config.DriveConfig(**OWN_PINS))
        self.assertEqual(len(board.wheels), 4)
        self.assertEqual(len({id(w) for w in board.wheels}), 4)
        board.wheels[3].value = 0.5                                  # only the rear right
        self.assertGreater(FakeDuty.made[19].duty, 0)
        self.assertTrue(all(FakeDuty.made[p].duty == 0 for p in (12, 13, 18)))
        board.close()
        self.assertEqual(self.pins.devices, {})

    def test_wheels_wired_in_parallel_cannot_be_mecanum(self):
        with self.assertRaises(ValueError):
            hardware.Tb6612(config.DriveConfig(drive_style="mecanum", dc_wheels=4))
        self.assertEqual(self.pins.devices, {})

    def test_one_rear_wheel_on_its_own_pins_is_not_enough(self):
        cfg = {**OWN_PINS, "dc_rear_right_pwm": -1, "dc_rear_right_in1": -1, "dc_rear_right_in2": -1}
        with self.assertRaises(ValueError):
            hardware.Tb6612(config.DriveConfig(**cfg))
        self.assertEqual(self.pins.devices, {})

    def test_two_wheels_cannot_be_mecanum(self):
        with self.assertRaises(ValueError):
            hardware.Tb6612(config.DriveConfig(drive_style="mecanum", dc_wheels=2))

    def test_tank_style_is_unchanged(self):
        board = hardware.Tb6612(config.DriveConfig(dc_wheels=4))
        self.assertIsNone(board.wheels)
        board.close()


def direction(pins, in1, in2):
    d = pins.devices
    return {(True, False): "forward", (False, True): "back"}.get((d[in1].value, d[in2].value), "stopped")


class TheDrive(FakeGpioCase):
    def drive(self, **kw):
        d = hardware.Drive(config.DriveConfig(**{**OWN_PINS, **kw}))
        self.addCleanup(d.close)
        return d

    def test_sliding_right_turns_the_diagonal_wheels_together(self):
        d = self.drive()
        self.assertTrue(d.mecanum)
        self.assertTrue(d.start(0, 0, 1.0, strafe=1.0))
        got = [direction(self.pins, a, b) for a, b in ((5, 6), (16, 20), (27, 22), (25, 4))]     # FL FR RL RR
        self.assertEqual(got, ["forward", "back", "back", "forward"])
        d.stop()
        self.assertEqual([FakeDuty.made[p].duty for p in (12, 13, 18, 19)], [0.0] * 4)

    def test_sliding_left_is_the_opposite(self):
        d = self.drive()
        d.start(0, 0, 1.0, strafe=-1.0)
        got = [direction(self.pins, a, b) for a, b in ((5, 6), (16, 20), (27, 22), (25, 4))]
        self.assertEqual(got, ["back", "forward", "forward", "back"])

    def test_the_speed_cap_applies_to_every_wheel(self):
        d = self.drive(max_speed=0.5)
        d.start(0, 0, 1.0, strafe=1.0)
        lo = d.cfg.dc_min_duty
        expect = lo + (1 - lo) * 0.5
        for pin in (12, 13, 18, 19):
            self.assertAlmostEqual(FakeDuty.made[pin].duty, expect)
        d.speed_cap = 0.2                                           # /speed lowers it live
        d.start(0, 0, 1.0, strafe=1.0)
        self.assertAlmostEqual(FakeDuty.made[12].duty, lo + (1 - lo) * 0.2)

    def test_a_spin_still_works_on_all_four(self):
        d = self.drive()
        d.start(-1, 1, 1.0)
        got = [direction(self.pins, a, b) for a, b in ((5, 6), (16, 20), (27, 22), (25, 4))]
        self.assertEqual(got, ["back", "forward", "back", "forward"])

    def test_the_wheel_flips_still_work(self):
        d = self.drive(right_invert=True, rear_left_invert=True)
        d.start(1, 1, 1.0)
        got = [direction(self.pins, a, b) for a, b in ((5, 6), (16, 20), (27, 22), (25, 4))]
        self.assertEqual(got, ["forward", "back", "back", "back"])  # FL ok, FR/RR flipped by right_invert, RL flipped by rear_left_invert

    def test_the_move_ends_by_itself_and_the_estop_cuts_everything(self):
        d = self.drive()
        d.start(0, 0, 0.1, strafe=1.0)
        time.sleep(0.4)
        self.assertFalse(d.moving)
        self.assertEqual([FakeDuty.made[p].duty for p in (12, 13, 18, 19)], [0.0] * 4)
        d.start(0, 0, 3.0, strafe=1.0)
        d.emergency_stop()
        self.assertEqual([FakeDuty.made[p].duty for p in (12, 13, 18, 19)], [0.0] * 4)
        self.assertFalse(self.pins.devices[21].value)                # standby low: both boards off
        self.assertFalse(d.start(0, 0, 1.0, strafe=1.0))

    def test_a_blocked_way_ahead_still_stops_a_forward_slide(self):
        class Ranger:
            def too_close(self):
                return 20
        d = hardware.Drive(config.DriveConfig(**OWN_PINS), ranger=Ranger())
        self.addCleanup(d.close)
        self.assertFalse(d.start(0.5, 0.5, 1.0, strafe=0.5))          # forward part refused by the distance sensor
        self.assertTrue(d.start(0, 0, 1.0, strafe=0.5))               # a pure sideways slide is not "forward"

    def test_a_tank_robot_refuses_to_slide(self):
        d = hardware.Drive(config.DriveConfig(), sim=True)
        self.addCleanup(d.close)
        self.assertFalse(d.mecanum)
        self.assertFalse(d.start(0, 0, 1.0, strafe=1.0))
        self.assertIn("mecanum", d.stop_reason)
        self.assertTrue(d.start(0.5, 0.5, 0.2))                       # ordinary moves are untouched

    def test_mecanum_on_servos_falls_back_to_a_tank(self):
        d = hardware.Drive(config.DriveConfig(type="servo", drive_style="mecanum"), sim=True)
        self.addCleanup(d.close)
        self.assertFalse(d.mecanum)

    def test_a_bad_setup_leaves_him_simulating_not_driving(self):
        d = hardware.Drive(config.DriveConfig(drive_style="mecanum", dc_wheels=4))       # wheels in parallel: refused
        self.addCleanup(d.close)
        self.assertTrue(d.sim)
        self.assertEqual(self.pins.devices, {})


class TheSetting(unittest.TestCase):
    def test_it_is_read_and_a_typo_is_refused(self):
        import tempfile
        self.assertEqual(config.Config().drive.drive_style, "tank")
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.toml"
            path.write_text('[drive]\ndrive_style = "mecanum"\n')
            self.assertEqual(config.load(path).drive.drive_style, "mecanum")
            path.write_text('[drive]\ndrive_style = "mecanium"\n')
            with self.assertRaises(ValueError):
                config.load(path)


class TheCommandsAndClaude(unittest.TestCase):
    def setUp(self):
        import bob
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        cfg = config.Config()
        cfg.stream.enabled = False
        self.cfg = cfg
        self.bob = bob
        self.ctrl = bob.Controller(cfg, sim=True, paused=True)
        self.addCleanup(self.ctrl.shutdown)

    def test_strafe_on_a_tank_robot_says_why(self):
        out = self.ctrl.handle("/strafe left")
        self.assertIn("can't move sideways", out)

    def test_strafe_usage(self):
        self.assertIn("usage", self.ctrl.handle("/strafe up"))

    def test_strafe_and_move_with_a_fourth_number_work_on_a_mecanum_robot(self):
        self.ctrl.drive.mecanum = True                               # (simulated wheels)
        calls = []
        self.ctrl.drive.move = lambda *a: calls.append(a) or 0.0
        self.assertIn("strafe=-0.60", self.ctrl.handle("/strafe left 0.3"))
        self.assertIn("strafe=+0.60", self.ctrl.handle("/strafe right"))
        self.ctrl.handle("/move 0.2 0.2 0.5 -0.4")
        time.sleep(0.2)
        self.assertEqual(sorted(calls), sorted([(0.0, 0.0, 0.3, -0.6), (0.0, 0.0, 0.8, 0.6), (0.2, 0.2, 0.5, -0.4)]))

    def test_the_estop_still_beats_a_strafe(self):
        self.ctrl.drive.mecanum = True
        self.ctrl.drive.estop.set()
        self.assertIn("E-stop", self.ctrl.handle("/strafe left"))

    def test_claude_only_sees_the_slide_moves_with_mecanum_wheels(self):
        import brain
        tank = brain.build_tools(3.0)
        mec = brain.build_tools(3.0, mecanum=True)
        enum = lambda tools: next(t for t in tools if t["name"] == "drive")["input_schema"]["properties"]["direction"]["enum"]
        self.assertNotIn("strafe_left", enum(tank))
        self.assertIn("strafe_left", enum(mec))
        self.assertIn("strafe_right", enum(mec))

    def test_claude_cannot_slide_a_tank_and_has_no_new_admin_tools(self):
        import brain
        names = {t["name"] for t in brain.build_tools(3.0, mecanum=True)}
        self.assertTrue(names.isdisjoint({"strafe", "shutdown", "update", "pair", "devices", "alerts", "quit"}))


if __name__ == "__main__":
    unittest.main()
