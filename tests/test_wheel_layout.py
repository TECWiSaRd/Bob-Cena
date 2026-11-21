import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
import hardware  # noqa: E402
from test_four_wheels import FakeDuty, FakePins, fake_make_duty  # noqa: E402
import types  # noqa: E402
import test_mecanum  # noqa: E402

# Board 2's channel A on its own pins (PWM 18, IN1 27, IN2 22); board 1 as in the manual.
A_ON_BOTH = dict(dc_wheels=4, dc_rear_left_pwm=18, dc_rear_left_in1=27, dc_rear_left_in2=22,
                 dc_left_wheels=["board1_a"], dc_right_wheels=["board2_a"], left_invert=False, right_invert=False)


class Base(test_mecanum.FakeGpioCase):
    def board(self, **kw):
        return hardware.Tb6612(config.DriveConfig(**{**A_ON_BOTH, **kw}))


class TheLayout(Base):
    def test_one_wheel_on_each_boards_a_channel(self):
        board = self.board()
        self.assertFalse(isinstance(board.left, hardware.MotorGroup) or isinstance(board.right, hardware.MotorGroup))
        board.left.value = 0.5
        self.assertGreater(FakeDuty.made[12].duty, 0)          # board 1 A is the left wheel
        self.assertEqual(FakeDuty.made[18].duty, 0.0)
        board.left.value = None
        board.right.value = 0.5
        self.assertGreater(FakeDuty.made[18].duty, 0)          # board 2 A is the right wheel
        self.assertEqual(FakeDuty.made[12].duty, 0.0)
        board.close()
        self.assertEqual(self.pins.devices, {})

    def test_channels_that_are_not_used_are_never_claimed(self):
        board = self.board()
        self.assertNotIn(13, FakeDuty.made)                    # board 1 B's PWM
        self.assertTrue(all(p not in self.pins.devices for p in (16, 20)))     # its direction pins
        self.assertEqual(set(self.pins.devices), {5, 6, 27, 22, 21})
        board.close()

    def test_a_wheel_uses_the_trim_of_the_side_it_is_on(self):
        board = self.board(right_trim=0.2, left_trim=0.0)
        board.left.value = 0.5
        board.right.value = 0.5
        lo = 0.25
        base = lo + (1 - lo) * 0.5
        self.assertAlmostEqual(FakeDuty.made[12].duty, base)
        self.assertAlmostEqual(FakeDuty.made[18].duty, min(1.0, base * 1.2))
        board.close()

    def test_a_flipped_rear_wheel_stays_flipped(self):
        board = self.board(rear_left_invert=True)
        board.right.value = 0.5
        d = self.pins.devices
        self.assertEqual((d[27].value, d[22].value), (False, True))        # reversed
        board.close()

    def test_the_default_layout_is_what_it_always_was(self):
        L = hardware.Tb6612.layout
        self.assertEqual(L(config.DriveConfig(), None, None), (["board1_a"], ["board1_b"]))
        self.assertEqual(L(config.DriveConfig(dc_wheels=4), None, None), (["board1_a"], ["board1_b"]))
        self.assertEqual(L(config.DriveConfig(dc_wheels=4), (1, 2, 3), (4, 5, 6)),
                         (["board1_a", "board2_a"], ["board1_b", "board2_b"]))

    def test_names_can_be_written_in_capitals(self):
        board = self.board(dc_left_wheels=["Board1_A"], dc_right_wheels=["BOARD2_A"])
        board.close()


class Mistakes(Base):
    def refused(self, **kw):
        with self.assertRaises(ValueError):
            self.board(**kw)
        self.assertEqual(self.pins.devices, {}, "a refused layout must not leave pins claimed")

    def test_only_one_side_set(self):
        self.refused(dc_right_wheels=[])

    def test_an_unknown_name(self):
        self.refused(dc_right_wheels=["board3_a"])

    def test_board_2_without_its_own_pins(self):
        self.refused(dc_rear_left_pwm=-1, dc_rear_left_in1=-1, dc_rear_left_in2=-1)

    def test_board_2_with_only_two_wheels(self):
        self.refused(dc_wheels=2)

    def test_the_same_channel_on_both_sides(self):
        self.refused(dc_left_wheels=["board1_a"], dc_right_wheels=["board1_a"])
        self.refused(dc_left_wheels=["board1_a", "board1_a"], dc_right_wheels=["board2_a"])

    def test_mecanum_does_not_take_a_layout(self):
        self.refused(drive_style="mecanum", dc_rear_right_pwm=19, dc_rear_right_in1=25, dc_rear_right_in2=4)


class OnTheRealDrive(Base):
    def test_the_stick_commands_reach_the_right_wheels(self):
        d = hardware.Drive(config.DriveConfig(**A_ON_BOTH))
        self.addCleanup(d.close)
        self.assertTrue(d.start(0.5, -0.5, 1.0))                 # a spin: left forward, right back
        dev = self.pins.devices
        self.assertEqual((dev[5].value, dev[6].value), (True, False))      # board 1 A forward
        self.assertEqual((dev[27].value, dev[22].value), (False, True))    # board 2 A backward
        d.stop()
        self.assertEqual((FakeDuty.made[12].duty, FakeDuty.made[18].duty), (0.0, 0.0))

    def test_a_bad_layout_leaves_him_simulating(self):
        d = hardware.Drive(config.DriveConfig(**{**A_ON_BOTH, "dc_right_wheels": ["board9_z"]}))
        self.addCleanup(d.close)
        self.assertTrue(d.sim)


class TheSetting(unittest.TestCase):
    def test_it_loads_and_a_wrong_type_is_refused(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "config.toml"
            path.write_text('[drive]\ndc_left_wheels = ["board1_a"]\ndc_right_wheels = ["board2_a"]\n')
            cfg = config.load(path)
            self.assertEqual((cfg.drive.dc_left_wheels, cfg.drive.dc_right_wheels), (["board1_a"], ["board2_a"]))
            path.write_text('[drive]\ndc_left_wheels = "board1_a"\n')
            with self.assertRaises(ValueError):
                config.load(path)
        self.assertEqual(config.DriveConfig().dc_left_wheels, [])


if __name__ == "__main__":
    unittest.main()
