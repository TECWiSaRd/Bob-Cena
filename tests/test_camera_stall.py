import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from hardware import Camera  # noqa: E402


class Source:
    name = "fake"

    def __init__(self):
        self.release = threading.Event()
        self.hang = False
        self.fail = False
        self.calls = 0

    def _go(self, value):
        self.calls += 1
        if self.fail:
            raise RuntimeError("Failed to queue buffer")
        if self.hang:
            self.release.wait(10)
        return value

    def jpeg(self):
        return self._go(b"jpeg")

    def frame(self):
        return self._go("frame")

    def start(self):
        pass

    def stop(self):
        pass

    def close(self):
        pass


def make():
    cam = Camera(config.CameraConfig(), sim=True)
    cam._src = Source()
    cam.STALL_S = 0.3
    return cam


class StallTests(unittest.TestCase):
    def test_normal_pictures_still_work(self):
        cam = make()
        self.assertEqual((cam.capture_jpeg(), cam.grab_bgr(), cam.stalled), (b"jpeg", "frame", False))

    def test_a_stuck_driver_does_not_freeze_other_callers(self):
        cam = make()
        cam._src.hang = True
        threading.Thread(target=cam.capture_jpeg, daemon=True).start()       # e.g. the dashboard's capture, now stuck
        time.sleep(0.5)
        self.assertTrue(cam.stalled)
        t0 = time.monotonic()
        self.assertIsNone(cam.grab_bgr())                                    # the tag scanner, the AI...
        self.assertIsNone(cam.capture_jpeg())
        self.assertFalse(cam.set_enabled(False))                             # ...and the /camera command return at once
        self.assertLess(time.monotonic() - t0, 0.5)
        self.assertEqual(cam._src.calls, 1)                                  # nobody queued up behind the stuck call
        cam._src.release.set()

    def test_it_recovers_when_the_driver_comes_back(self):
        cam = make()
        cam._src.hang = True
        threading.Thread(target=cam.capture_jpeg, daemon=True).start()
        time.sleep(0.5)
        cam._src.hang = False
        cam._src.release.set()
        time.sleep(0.2)
        self.assertFalse(cam.stalled)
        self.assertEqual(cam.capture_jpeg(), b"jpeg")

    def test_a_driver_error_means_no_picture_not_a_crash(self):
        cam = make()
        cam._src.fail = True
        self.assertIsNone(cam.capture_jpeg())
        self.assertIsNone(cam.grab_bgr())
        cam._src.fail = False
        self.assertEqual(cam.capture_jpeg(), b"jpeg")

    def test_check_shows_why_a_picture_failed(self):
        import os
        import bob
        import selfcheck
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        cfg = config.Config()
        cfg.stream.enabled = False
        ctrl = bob.Controller(cfg, sim=True, paused=True)
        self.addCleanup(ctrl.shutdown)
        cam = make()
        cam._src.fail = True
        ctrl.camera = cam
        rows = {n: (lv, d) for lv, n, d in selfcheck.run_checks(ctrl, Path("."))}
        self.assertIn("Failed to queue buffer", rows["camera"][1])

    def test_the_watchdog_can_fire_again_for_a_later_hang(self):
        cam = make()
        seen = []
        cam.watch(0.4, seen.append, poll=0.05)
        for _ in range(2):
            cam._src.hang = True
            cam._src.release.clear()
            threading.Thread(target=cam.capture_jpeg, daemon=True).start()
            time.sleep(0.8)
            cam._src.hang = False
            cam._src.release.set()
            time.sleep(0.3)
        self.assertEqual(len(seen), 2)
        cam.close()

    def test_check_reports_a_stalled_camera(self):
        import os
        import bob
        import selfcheck
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        cfg = config.Config()
        cfg.stream.enabled = False
        ctrl = bob.Controller(cfg, sim=True, paused=True)
        self.addCleanup(ctrl.shutdown)
        cam = make()
        cam._src.hang = True
        ctrl.camera = cam
        threading.Thread(target=cam.capture_jpeg, daemon=True).start()
        time.sleep(0.5)
        rows = {n: (lv, d) for lv, n, d in selfcheck.run_checks(ctrl, Path("."))}
        self.assertEqual(rows["camera"][0], "FAIL")
        self.assertIn("NOT RESPONDING", rows["camera"][1])
        cam._src.release.set()


class WatchdogTests(unittest.TestCase):
    def test_a_long_hang_calls_for_help_exactly_once(self):
        cam = make()
        cam._src.hang = True
        seen = []
        cam.watch(0.6, seen.append, poll=0.05)
        threading.Thread(target=cam.capture_jpeg, daemon=True).start()
        time.sleep(1.2)
        self.assertEqual(len(seen), 1)
        self.assertGreaterEqual(seen[0], 0.6)
        cam._src.release.set()
        cam.close()

    def test_a_short_hang_or_normal_use_never_does(self):
        cam = make()
        seen = []
        cam.watch(0.6, seen.append, poll=0.05)
        for _ in range(5):
            cam.capture_jpeg()
        cam._src.hang = True
        threading.Thread(target=cam.capture_jpeg, daemon=True).start()
        time.sleep(0.3)
        cam._src.release.set()                               # it recovers before the limit
        time.sleep(0.8)
        self.assertEqual(seen, [])
        cam.close()

    def test_zero_turns_it_off(self):
        cam = make()
        cam._src.hang = True
        seen = []
        cam.watch(0, seen.append, poll=0.05)
        threading.Thread(target=cam.capture_jpeg, daemon=True).start()
        time.sleep(0.5)
        self.assertEqual(seen, [])
        cam._src.release.set()


class RestartTests(unittest.TestCase):
    def setUp(self):
        import os
        import bob
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        cfg = config.Config()
        cfg.stream.enabled = False
        self.ctrl = bob.Controller(cfg, sim=True, paused=True)
        self.stopped = []
        self.ctrl.drive.stop = lambda *a, **k: self.stopped.append("stop")
        self.ctrl.drive.close = lambda: self.stopped.append("close")
        self.addCleanup(lambda: None)

    def test_under_the_service_the_wheels_stop_and_bob_exits_with_a_failure_code(self):
        import os
        codes = []
        os.environ["BOB_SUPERVISED"] = "1"
        self.addCleanup(os.environ.pop, "BOB_SUPERVISED", None)
        self.ctrl.camera_stuck(20.0, exit_fn=codes.append)
        self.assertEqual(self.stopped, ["stop", "close"])          # wheels off BEFORE the process goes
        self.assertEqual(codes, [75])

    def test_started_by_hand_he_stays_up_and_says_what_to_do(self):
        import os
        os.environ.pop("BOB_SUPERVISED", None)
        codes = []
        self.ctrl.camera_stuck(20.0, exit_fn=codes.append)
        self.assertEqual(codes, [])
        self.assertEqual(self.stopped, ["stop"])                   # wheels stopped, but the motor driver is NOT closed: Bob carries on


if __name__ == "__main__":
    unittest.main()
