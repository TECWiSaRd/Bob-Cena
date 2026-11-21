import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
import hardware  # noqa: E402
import test_mecanum  # noqa: E402
from test_four_wheels import FakeDuty  # noqa: E402


def duty(v, lo=0.25, trim=0.0):
    return (lo + (1 - lo) * abs(v)) * (1 + trim)


class TheWheels(test_mecanum.FakeGpioCase):
    def drive(self, **kw):
        d = hardware.Drive(config.DriveConfig(**{"left_invert": False, "right_invert": False, **kw}))
        self.addCleanup(d.close)
        return d

    def test_a_back_trim_only_applies_when_the_wheel_is_driven_backward(self):
        d = self.drive(back_right_trim=0.2)
        d.speed_cap = 1.0
        d.start(0.5, 0.5, 1.0)
        self.assertAlmostEqual(FakeDuty.made[13].duty, duty(0.5))                  # forward: no trim
        d.start(-0.5, -0.5, 1.0)
        self.assertAlmostEqual(FakeDuty.made[13].duty, duty(0.5, trim=0.2))         # backward: +20%
        self.assertAlmostEqual(FakeDuty.made[12].duty, duty(0.5))                  # the left wheel has no back trim

    def test_forward_and_back_trims_are_separate(self):
        d = self.drive(left_trim=0.1, back_left_trim=-0.1)
        d.speed_cap = 1.0
        d.start(0.5, 0.5, 1.0)
        self.assertAlmostEqual(FakeDuty.made[12].duty, duty(0.5, trim=0.1))
        d.start(-0.5, -0.5, 1.0)
        self.assertAlmostEqual(FakeDuty.made[12].duty, duty(0.5, trim=-0.1))

    def test_the_trim_follows_the_command_not_the_electrical_direction(self):
        # a robot with inverted wheels (OG Bob): a forward command reaches the motor as a negative value, but it is still 'forward'
        d = self.drive(left_invert=True, right_invert=True, back_right_trim=0.2)
        d.speed_cap = 1.0
        d.start(0.5, 0.5, 1.0)
        self.assertAlmostEqual(FakeDuty.made[13].duty, duty(0.5))                  # still forward: no back trim
        d.start(-0.5, -0.5, 1.0)
        self.assertAlmostEqual(FakeDuty.made[13].duty, duty(0.5, trim=0.2))

    def test_in_a_spin_the_backward_wheel_uses_its_back_trim(self):
        d = self.drive(back_left_trim=0.1, left_trim=0.0)
        d.speed_cap = 1.0
        d.start(-0.5, 0.5, 1.0)                                                    # a left spin: the left wheel goes backward
        self.assertAlmostEqual(FakeDuty.made[12].duty, duty(0.5, trim=0.1))
        self.assertAlmostEqual(FakeDuty.made[13].duty, duty(0.5))

    def test_a_four_wheel_side_uses_it_on_both_wheels(self):
        d = hardware.Drive(config.DriveConfig(left_invert=False, right_invert=False, dc_wheels=4, back_left_trim=0.1,
                                              dc_rear_left_pwm=18, dc_rear_left_in1=27, dc_rear_left_in2=22,
                                              dc_rear_right_pwm=19, dc_rear_right_in1=25, dc_rear_right_in2=4))
        self.addCleanup(d.close)
        d.speed_cap = 1.0
        d.start(-0.5, -0.5, 1.0)
        self.assertAlmostEqual(FakeDuty.made[12].duty, duty(0.5, trim=0.1))
        self.assertAlmostEqual(FakeDuty.made[18].duty, duty(0.5, trim=0.1))

    def test_mecanum_judges_each_wheel_by_its_own_command(self):
        d = hardware.Drive(config.DriveConfig(**{**test_mecanum.OWN_PINS, "back_left_trim": 0.1, "back_right_trim": 0.2}))
        self.addCleanup(d.close)
        d.speed_cap = 1.0
        d.start(0, 0, 1.0, strafe=0.5)           # sliding right: front left and rear right forward, the other two backward
        self.assertAlmostEqual(FakeDuty.made[12].duty, duty(0.5))                  # front left: forward
        self.assertAlmostEqual(FakeDuty.made[13].duty, duty(0.5, trim=0.2))        # front right: backward, back_right_trim
        self.assertAlmostEqual(FakeDuty.made[18].duty, duty(0.5, trim=0.1))        # rear left: backward, back_left_trim
        self.assertAlmostEqual(FakeDuty.made[19].duty, duty(0.5))                  # rear right: forward

    def test_without_any_back_trim_nothing_changes(self):
        d = self.drive()
        d.speed_cap = 1.0
        for cmd in ((0.5, 0.5), (-0.5, -0.5), (-0.5, 0.5)):
            d.start(*cmd, 1.0)
            self.assertAlmostEqual(FakeDuty.made[12].duty, duty(0.5))


class TheCommand(unittest.TestCase):
    def setUp(self):
        import bob
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        self.bob = bob
        cfg = config.Config()
        cfg.stream.enabled = False
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._old = bob.TUNING
        bob.TUNING = Path(self.tmp.name) / "tuning.json"                 # never touch the real one
        self.addCleanup(setattr, bob, "TUNING", self._old)
        self.ctrl = bob.Controller(cfg, sim=True, paused=True)
        self.addCleanup(self.ctrl.shutdown)
        self.d = self.ctrl.cfg.drive

    def test_back_trims_can_be_set_and_are_saved(self):
        out = self.ctrl.handle("/trim back left 0.03")
        self.assertEqual(self.d.back_left_trim, 0.03)
        self.assertIn("backing up: left +0.030", out)
        self.ctrl.handle("/trim back right -0.02")
        self.assertEqual(self.d.back_right_trim, -0.02)
        saved = json.loads((Path(self.tmp.name) / "tuning.json").read_text())
        self.assertEqual((saved["back_left_trim"], saved["back_right_trim"]), (0.03, -0.02))
        self.assertEqual((self.d.left_trim, self.d.right_trim), (0.0, 0.0))                   # the forward trims are untouched

    def test_they_are_limited_like_the_others(self):
        self.ctrl.handle("/trim back right 3")
        self.assertEqual(self.d.back_right_trim, 0.5)

    def test_reset_and_back_reset(self):
        for line in ("/trim left 0.05", "/trim back left 0.03", "/trim back right 0.04"):
            self.ctrl.handle(line)
        self.ctrl.handle("/trim back reset")
        self.assertEqual((self.d.back_left_trim, self.d.back_right_trim, self.d.left_trim), (0.0, 0.0, 0.05))
        self.ctrl.handle("/trim back left 0.03")
        self.ctrl.handle("/trim reset")
        self.assertEqual((self.d.left_trim, self.d.back_left_trim), (0.0, 0.0))

    def test_bad_input_changes_nothing_and_says_how(self):
        for line in ("/trim back", "/trim back up 0.1", "/trim back left lots", "/trim left lots", "/trim sideways 1"):
            self.assertIn("usage", self.ctrl.handle(line), line)
        self.assertEqual((self.d.back_left_trim, self.d.left_trim), (0.0, 0.0))

    def test_show_lists_both(self):
        text = self.ctrl.handle("/trim")
        self.assertIn("when backing up", text)
        self.assertIn("backing up", self.ctrl.handle("/calibrate show"))

    def fake_calibration(self, result):
        calls = []

        class FakeCalibrator:
            def __init__(self, *a, **k):
                self.cancel = False

            def straight(self, **kw):
                calls.append(kw)
                return dict(result)
        self.bob_cal, self.bob.Calibrator = self.bob.Calibrator, FakeCalibrator
        self.addCleanup(setattr, self.bob, "Calibrator", self.bob_cal)
        self.ctrl.camera.enabled = True
        self.ctrl.camera.grab_bgr = lambda: object()
        return calls

    def run_calibration(self, line):
        import time
        out = self.ctrl.handle(line)
        end = time.time() + 3
        while self.ctrl.calibrating is not None and time.time() < end:
            time.sleep(0.01)
        return out

    def test_a_backing_up_only_run_changes_only_the_back_trims_and_saves_them(self):
        calls = self.fake_calibration({"left_trim": 0.0, "right_trim": 0.0, "back_left_trim": 0.0, "back_right_trim": -0.056,
                                       "back_drift_before": -2.5})
        self.d.right_trim, self.d.left_trim = 0.031, 0.01                 # earlier forward results
        self.run_calibration("/calibrate straight go back")
        self.assertEqual(calls[0]["forward"], False)
        self.assertEqual((self.d.left_trim, self.d.right_trim), (0.01, 0.031))     # untouched, even though the fake reported 0.0
        self.assertEqual(self.d.back_right_trim, -0.056)
        saved = json.loads((Path(self.tmp.name) / "tuning.json").read_text())
        self.assertEqual((saved["right_trim"], saved["left_trim"], saved["back_right_trim"]), (0.031, 0.01, -0.056))

    def test_a_forward_only_run_leaves_the_back_trims_alone(self):
        calls = self.fake_calibration({"left_trim": 0.0, "right_trim": -0.07, "drift_before": 3.9, "drift_probe": 7.0})
        self.d.back_right_trim, self.d.back_left_trim = -0.02, 0.01
        self.run_calibration("/calibrate straight go forward")
        self.assertEqual((calls[0]["reverse"], calls[0]["forward"]), (False, True))
        self.assertEqual(self.d.right_trim, -0.07)
        self.assertEqual((self.d.back_left_trim, self.d.back_right_trim), (0.01, -0.02))
        saved = json.loads((Path(self.tmp.name) / "tuning.json").read_text())
        self.assertEqual((saved["right_trim"], saved["back_right_trim"]), (-0.07, -0.02))

    def test_a_full_run_records_both(self):
        calls = self.fake_calibration({"left_trim": 0.0, "right_trim": -0.07, "drift_before": 3.9, "drift_probe": 7.0,
                                       "back_left_trim": 0.0, "back_right_trim": -0.056, "back_drift_before": -2.5})
        self.run_calibration("/calibrate straight go 0.6")
        self.assertEqual((calls[0]["seconds"], calls[0]["reverse"], calls[0]["forward"]), (0.6, True, True))
        saved = json.loads((Path(self.tmp.name) / "tuning.json").read_text())
        self.assertEqual((saved["right_trim"], saved["back_right_trim"]), (-0.07, -0.056))

    def test_a_failed_run_changes_and_saves_nothing(self):
        class Failing:
            def __init__(self, *a, **k):
                self.cancel = False

            def straight(self, **kw):
                raise RuntimeError("couldn't measure the drift: too plain")
        old, self.bob.Calibrator = self.bob.Calibrator, Failing
        self.addCleanup(setattr, self.bob, "Calibrator", old)
        self.ctrl.camera.enabled = True
        self.ctrl.camera.grab_bgr = lambda: object()
        self.d.right_trim = 0.031
        self.run_calibration("/calibrate straight go")
        self.assertEqual(self.d.right_trim, 0.031)
        self.assertFalse((Path(self.tmp.name) / "tuning.json").exists())

    def test_asking_for_both_parts_at_once_is_a_mistake_and_says_so(self):
        self.ctrl.camera.enabled = True
        self.ctrl.camera.grab_bgr = lambda: object()
        self.assertIn("choose one", self.ctrl.handle("/calibrate straight go forward back"))
        self.assertIn("usage", self.ctrl.handle("/calibrate straight go sideways"))

    def test_saved_back_trims_come_back_after_a_restart(self):
        (Path(self.tmp.name) / "tuning.json").write_text(json.dumps({"back_left_trim": 0.04, "back_right_trim": -0.6}))
        cfg = config.DriveConfig()
        self.bob.load_tuning(cfg)
        self.assertEqual(cfg.back_left_trim, 0.04)
        self.assertEqual(cfg.back_right_trim, -0.5)                      # limited on the way in, too


if __name__ == "__main__":
    unittest.main()
