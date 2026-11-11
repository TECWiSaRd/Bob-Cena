import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import hardware  # noqa: E402


class FakePins:
    """A pretend gpiozero that remembers every pin that was claimed and refuses a pin claimed twice (like the real one)."""

    def __init__(self):
        self.devices = {}

    def module(self):
        pins = self

        class DigitalOutputDevice:
            def __init__(self, pin, initial_value=False):
                if pin in pins.devices:
                    raise RuntimeError(f"pin {pin} is already in use")
                pins.devices[pin] = self
                self.pin, self.value, self.closed = pin, bool(initial_value), False

            def close(self):
                self.closed = True
                pins.devices.pop(self.pin, None)

        m = types.ModuleType("gpiozero")
        m.DigitalOutputDevice = DigitalOutputDevice
        return m


class FakeDuty:
    made = {}

    def __init__(self, pin):
        self.pin, self.duty, self.closed = pin, 0.0, False

    def set(self, d):
        self.duty = d

    def close(self):
        self.closed = True


def fake_make_duty(pin, hz):
    if pin in FakeDuty.made and not FakeDuty.made[pin].closed:
        raise RuntimeError(f"pwm {pin} in use")
    FakeDuty.made[pin] = FakeDuty(pin)
    return FakeDuty.made[pin]


class FourWheelTests(unittest.TestCase):
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

    def cfg(self, **kw):
        return config.DriveConfig(**kw)

    def test_two_wheels_is_unchanged(self):
        board = hardware.Tb6612(self.cfg())
        self.assertIsInstance(board.left, hardware.DcMotor)
        board.left.value = 0.5
        self.assertGreater(FakeDuty.made[12].duty, 0)
        board.close()
        self.assertEqual(self.pins.devices, {})

    def test_four_wheels_in_parallel_needs_no_extra_pins(self):
        board = hardware.Tb6612(self.cfg(dc_wheels=4))
        self.assertIsInstance(board.left, hardware.DcMotor)     # the rear board follows the same wires
        self.assertEqual(set(self.pins.devices), {5, 6, 16, 20, 21})     # the same five pins as with two wheels
        board.close()

    def test_a_rear_wheel_on_its_own_pins_moves_with_the_front_one(self):
        cfg = self.cfg(dc_wheels=4, dc_rear_left_pwm=18, dc_rear_left_in1=27, dc_rear_left_in2=22,
                       dc_rear_right_pwm=19, dc_rear_right_in1=25, dc_rear_right_in2=4, dc_rear_standby=17)
        board = hardware.Tb6612(cfg)
        self.assertIsInstance(board.left, hardware.MotorGroup)
        board.left.value = 0.6
        board.right.value = -0.6
        self.assertGreater(FakeDuty.made[12].duty, 0)
        self.assertEqual(FakeDuty.made[12].duty, FakeDuty.made[18].duty)
        self.assertEqual(FakeDuty.made[13].duty, FakeDuty.made[19].duty)
        dev = self.pins.devices
        self.assertEqual((dev[5].value, dev[6].value), (dev[27].value, dev[22].value))      # same direction front and rear
        self.assertEqual((dev[16].value, dev[20].value), (dev[25].value, dev[4].value))
        board.left.value = None
        self.assertEqual(FakeDuty.made[18].duty, 0.0)
        board.close()
        self.assertEqual(self.pins.devices, {})

    def test_a_backwards_rear_wheel_can_be_flipped(self):
        cfg = self.cfg(dc_wheels=4, dc_rear_left_pwm=18, dc_rear_left_in1=27, dc_rear_left_in2=22, rear_left_invert=True)
        board = hardware.Tb6612(cfg)
        board.left.value = 0.5
        dev = self.pins.devices
        self.assertEqual((dev[5].value, dev[6].value), (True, False))
        self.assertEqual((dev[27].value, dev[22].value), (False, True))
        board.close()

    def test_standby_cuts_both_boards(self):
        cfg = self.cfg(dc_wheels=4, dc_rear_standby=17)
        board = hardware.Tb6612(cfg)
        dev = self.pins.devices
        self.assertTrue(dev[21].value and dev[17].value)
        board.standby(False)
        self.assertFalse(dev[21].value or dev[17].value)
        board.close()

    def test_half_a_set_of_rear_pins_is_refused_and_nothing_is_left_claimed(self):
        with self.assertRaises(ValueError):
            hardware.Tb6612(self.cfg(dc_wheels=4, dc_rear_left_pwm=18))
        self.assertEqual(self.pins.devices, {})

    def test_a_clash_with_a_pin_already_used_frees_everything(self):
        with self.assertRaises(RuntimeError):
            hardware.Tb6612(self.cfg(dc_wheels=4, dc_rear_left_pwm=18, dc_rear_left_in1=5, dc_rear_left_in2=22))
        self.assertEqual(self.pins.devices, {})

    def test_only_two_or_four_wheels(self):
        with self.assertRaises(ValueError):
            hardware.Tb6612(self.cfg(dc_wheels=3))
        self.assertEqual(self.pins.devices, {})

    def test_rear_pins_are_ignored_for_two_wheels(self):
        board = hardware.Tb6612(self.cfg(dc_rear_left_pwm=18))
        self.assertIsInstance(board.left, hardware.DcMotor)
        board.close()

    def test_the_drive_stops_every_wheel_on_estop(self):
        cfg = self.cfg(dc_wheels=4, dc_rear_left_pwm=18, dc_rear_left_in1=27, dc_rear_left_in2=22, dc_rear_standby=17)
        d = hardware.Drive(cfg)
        self.assertFalse(d.sim)
        d.start(0.5, 0.5, 2.0)
        self.assertGreater(FakeDuty.made[18].duty, 0)
        d.emergency_stop()
        self.assertEqual(FakeDuty.made[18].duty, 0.0)
        self.assertFalse(self.pins.devices[17].value)
        d.close()


if __name__ == "__main__":
    unittest.main()
