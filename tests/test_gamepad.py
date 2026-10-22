import os
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import gamepad  # noqa: E402
from gamepad import AXIS, BUTTON, EVENT, INIT, Gamepad  # noqa: E402

A, B, Y, LB, BACK, START = 0, 1, 3, 4, 6, 7
LX, LY = 0, 1
FULL = 32767


class FakeCtrl:
    def __init__(self):
        self.drive_mode = False
        self.moves, self.stops, self.estops, self.handled, self.talks = [], 0, [], [], 0
        self.drive = SimpleNamespace(stop=self._stop, estop=threading.Event())
        self.listener = SimpleNamespace(ptt_toggle=self._talk)

    def _stop(self):
        self.stops += 1

    def driving_for(self, who):
        return self.drive_mode and who == "gamepad"

    def leave_drive(self, who):
        if who == "gamepad":
            self.drive_mode = False

    def _talk(self):
        self.talks += 1
        return "talking"

    def manual(self, l, r, s):
        self.moves.append((round(l, 2), round(r, 2), s))

    def estop(self, source):
        self.estops.append(source)
        self.drive_mode = False

    def handle(self, line, **k):
        self.handled.append(line)
        if line == "/drive":
            self.drive_mode = True
        return "ok"


class Clock:
    t = 100.0

    def __call__(self):
        return self.t


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.ctrl, self.clock = FakeCtrl(), Clock()
        self.pad = Gamepad(config.GamepadConfig(), self.ctrl, clock=self.clock)

    def stick(self, x=0.0, y=0.0):
        self.pad.event(AXIS, LX, int(x * FULL))
        self.pad.event(AXIS, LY, int(y * FULL))

    def press(self, n):
        self.pad.event(BUTTON, n, 1)
        self.pad.event(BUTTON, n, 0)

    def test_stick_wobble_is_ignored_and_full_deflection_is_full(self):
        self.stick(0.1, -0.1)
        self.assertEqual(self.pad.wheels(), (0.0, 0.0))
        self.stick(0, -1.0)
        self.assertEqual(self.pad.wheels(), (1.0, 1.0))
        self.stick(0, 1.0)
        self.assertEqual(self.pad.wheels(), (-1.0, -1.0))

    def test_turning_and_arcs(self):
        self.stick(1.0, 0)
        self.assertEqual(self.pad.wheels(), (1.0, -1.0))
        self.stick(1.0, -1.0)
        l, r = self.pad.wheels()
        self.assertEqual((l, r), (1.0, 0.0))                  # forward and right: an arc, never above full speed

    def test_slow_button(self):
        self.stick(0, -1.0)
        self.pad.event(BUTTON, LB, 1)
        self.assertEqual(self.pad.wheels(), (0.4, 0.4))

    def test_sticks_do_nothing_until_manual_driving_is_on(self):
        self.stick(0, -1.0)
        self.pad.tick()
        self.assertEqual(self.ctrl.moves, [])
        self.press(START)
        self.assertEqual(self.ctrl.handled, ["/drive"])
        self.pad.tick()
        self.assertEqual(self.ctrl.moves, [(1.0, 1.0, gamepad.PULSE_S)])

    def test_centering_the_stick_stops_once(self):
        self.press(START)
        self.stick(0, -1.0)
        self.pad.tick()
        self.stick(0, 0)
        self.pad.tick()
        self.pad.tick()
        self.assertEqual(self.ctrl.stops, 1)

    def test_start_again_leaves_drive_mode_and_stops(self):
        self.press(START)
        self.press(START)
        self.assertFalse(self.ctrl.drive_mode)
        self.assertEqual(self.ctrl.stops, 1)

    def test_b_is_always_the_emergency_stop(self):
        self.press(B)
        self.assertEqual(self.ctrl.estops, ["gamepad"])

    def test_estop_blocks_driving_even_if_the_stick_is_held(self):
        self.press(START)
        self.stick(0, -1.0)
        self.ctrl.drive.estop.set()
        self.pad.tick()
        self.assertEqual(self.ctrl.moves, [])

    def test_y_resumes_and_a_talks(self):
        self.press(Y)
        self.press(A)
        self.assertEqual(self.ctrl.handled, ["/resume"])
        self.assertEqual(self.ctrl.talks, 1)

    def test_releasing_the_estop_needs_a_long_hold_of_back(self):
        self.pad.event(BUTTON, BACK, 1)
        self.clock.t += 1.0
        self.pad.tick()
        self.assertNotIn("/clear", self.ctrl.handled)
        self.clock.t += 1.0
        self.pad.tick()
        self.assertEqual(self.ctrl.handled, ["/clear"])
        self.pad.tick()
        self.assertEqual(self.ctrl.handled, ["/clear"])        # once per hold
        self.pad.event(BUTTON, BACK, 0)

    def test_a_short_tap_of_back_does_not_release_it(self):
        self.pad.event(BUTTON, BACK, 1)
        self.clock.t += 0.5
        self.pad.event(BUTTON, BACK, 0)
        self.clock.t += 5
        self.pad.tick()
        self.assertEqual(self.ctrl.handled, [])

    def test_the_state_sent_on_connect_never_acts(self):
        self.pad.event(BUTTON | INIT, B, 1)
        self.pad.event(BUTTON | INIT, START, 1)
        self.pad.event(AXIS | INIT, LY, -FULL)
        self.assertEqual((self.ctrl.estops, self.ctrl.handled), ([], []))
        self.assertTrue(self.pad.buttons[B])                   # but it is remembered, so releasing B later is normal
        self.pad.event(BUTTON, B, 0)
        self.pad.event(BUTTON, B, 1)
        self.assertEqual(self.ctrl.estops, ["gamepad"])

    def test_holding_a_button_does_not_repeat_it(self):
        self.pad.event(BUTTON, B, 1)
        self.pad.event(BUTTON, B, 1)
        self.assertEqual(self.ctrl.estops, ["gamepad"])


def wait_for(fn, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if fn():
            return True
        time.sleep(0.01)
    return False


def packet(kind, number, value):
    return EVENT.pack(0, value, kind, number)


class DeviceTests(unittest.TestCase):
    def start(self):
        self.r, self.w = os.pipe()
        os.set_blocking(self.r, False)
        self.ctrl = FakeCtrl()
        self.pad = Gamepad(config.GamepadConfig(), self.ctrl, find=lambda: ["/dev/input/js0"],
                           opener=lambda path: self.r)
        self.pad.start()
        self.addCleanup(self.pad.stop)

    def test_reads_real_events_from_a_device(self):
        self.start()
        os.write(self.w, packet(BUTTON, START, 1) + packet(BUTTON, START, 0) + packet(AXIS, LY, -FULL))
        self.assertTrue(wait_for(lambda: self.ctrl.moves))
        self.assertEqual(self.ctrl.moves[0][:2], (1.0, 1.0))

    def test_unplugging_stops_the_wheels(self):
        self.start()
        os.write(self.w, packet(BUTTON, START, 1) + packet(AXIS, LY, -FULL))
        self.assertTrue(wait_for(lambda: self.ctrl.moves))
        before = self.ctrl.stops
        os.close(self.w)                                       # the controller disappears with the stick held
        self.assertTrue(wait_for(lambda: self.ctrl.stops > before))
        self.assertTrue(wait_for(lambda: self.pad.connected == ""))
        self.assertEqual(self.pad.axes, {})

    def test_no_controller_is_quiet_and_harmless(self):
        ctrl = FakeCtrl()
        pad = Gamepad(config.GamepadConfig(), ctrl, find=lambda: [])
        pad.start()
        time.sleep(0.2)
        pad.stop()
        self.assertEqual((pad.describe(), ctrl.moves, ctrl.estops), ("no controller found", [], []))


class ConfigTests(unittest.TestCase):
    def test_off_by_default_and_wired_into_the_robot(self):
        self.assertFalse(config.Config().gamepad.enabled)
        import bob
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        cfg = config.Config()
        cfg.stream.enabled = False
        cfg.gamepad.enabled = True
        ctrl = bob.Controller(cfg, sim=True, paused=True)
        self.addCleanup(ctrl.shutdown)
        self.assertIsNotNone(ctrl.gamepad)
        import selfcheck
        rows = {n: (lv, d) for lv, n, d in selfcheck.run_checks(ctrl, Path("."))}
        self.assertEqual(rows["controller"][0], "WARN")


if __name__ == "__main__":
    unittest.main()


class SeparateFromTheConsoleTests(unittest.TestCase):
    """The controller and the tmux console are different drivers on the real controller."""

    def setUp(self):
        import bob
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        cfg = config.Config()
        cfg.stream.enabled = False
        self.ctrl = bob.Controller(cfg, sim=True, paused=True)
        self.addCleanup(self.ctrl.shutdown)
        self.pad = Gamepad(config.GamepadConfig(), self.ctrl, clock=Clock())

    def press(self, n):
        self.pad.event(BUTTON, n, 1)
        self.pad.event(BUTTON, n, 0)

    def test_starting_and_stopping_on_the_controller_never_changes_the_consoles_drive(self):
        self.press(START)
        self.assertTrue(self.ctrl.driving_for("gamepad"))
        self.assertFalse(self.ctrl.driving_for(None))              # the owner's tmux console is not switched to driving
        self.press(START)
        self.assertFalse(self.ctrl.drive_mode)
        self.assertFalse(self.ctrl.driving_for(None))

    def test_the_console_driving_is_not_stopped_or_started_by_the_controller(self):
        self.ctrl.handle("/drive")                                  # the owner drives from the console
        self.press(START)                                           # a friend starts on the controller...
        self.press(START)                                           # ...and stops
        self.assertTrue(self.ctrl.driving_for(None))                # the owner is still driving, undisturbed
        self.assertFalse(self.ctrl.driving_for("gamepad"))

    def test_the_stick_only_moves_him_while_the_controller_itself_is_driving(self):
        moves = []
        self.ctrl.manual = lambda l, r, s: moves.append((l, r))
        self.ctrl.handle("/drive")                                  # the console is driving, the controller is not
        self.pad.event(AXIS, LY, -FULL)
        self.pad.tick()
        self.assertEqual(moves, [])
        self.press(START)
        self.pad.tick()
        self.assertEqual(moves, [(1.0, 1.0)])

    def test_drive_all_includes_a_connected_controller(self):
        self.pad.connected = "Xbox Wireless Controller"
        self.ctrl.gamepad = self.pad
        self.ctrl.handle("/drive all")
        self.assertTrue(self.ctrl.driving_for("gamepad") and self.ctrl.driving_for(None))
