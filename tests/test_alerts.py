import os
import sys
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from alerts import Alerts, clear_running, mark_running, problems, vitals, vitals_line  # noqa: E402

HB = "https://hc-ping.com/aaaa-bbbb-secret"
NTFY = "https://ntfy.sh/bob-secret-topic"


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


class FakeNet:
    """Stands in for urlopen: records every request, and can fail."""

    def __init__(self):
        self.requests = []
        self.fail = None

    def __call__(self, req, timeout=None):
        self.requests.append((req.full_url, req.data.decode(), dict(req.header_items())))
        if self.fail:
            raise self.fail
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return b"ok"


def wait_for(fn, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if fn():
            return True
        time.sleep(0.01)
    return False


def make(net=None, clock=None, hb=HB, ntfy=NTFY, sample=None, **cfg):
    net = net or FakeNet()
    cfg.setdefault("enabled", True)
    a = Alerts(config.AlertsConfig(**cfg), "Bob", hb, ntfy, opener=net, clock=clock or Clock(),
               sample=sample or (lambda base: {"load": 0.2, "mem_mb": 2000, "temp_c": 45.0, "throttled": 0, "disk_gb": 20.0}))
    return a, net


class NotifyTests(unittest.TestCase):
    def test_a_message_is_sent_from_the_background_with_a_title_and_priority(self):
        a, net = make()
        a.start()
        self.addCleanup(a.stop)
        self.assertTrue(a.notify("estop", "Emergency stop (console)", "high"))
        self.assertTrue(wait_for(lambda: any(u == NTFY for u, *_ in net.requests)))
        url, body, headers = [r for r in net.requests if r[0] == NTFY][0]
        self.assertEqual(body, "Emergency stop (console)")
        self.assertEqual((headers["Title"], headers["Priority"]), ("Bob", "high"))

    def test_each_kind_is_limited_so_a_loop_cannot_flood_a_phone(self):
        clock = Clock()
        a, _ = make(clock=clock, cooldown_s=300.0)
        self.assertTrue(a.notify("estop", "one"))
        self.assertFalse(a.notify("estop", "two"))
        self.assertTrue(a.notify("camera", "a different kind is separate"))
        clock.t += 301
        self.assertTrue(a.notify("estop", "three"))

    def test_only_the_chosen_events_send(self):
        a, _ = make(notify=["estop"])
        self.assertFalse(a.notify("camera", "not wanted"))
        self.assertTrue(a.notify("estop", "wanted"))
        self.assertTrue(a.notify("camera", "forced anyway", force=True))

    def test_off_or_without_an_address_does_nothing_and_never_raises(self):
        a, net = make(enabled=False)
        self.assertFalse(a.notify("estop", "x"))
        a2, _ = make(ntfy="")
        self.assertFalse(a2.notify("estop", "x"))
        a2.start(), a2.stop(0.1)
        self.assertEqual(net.requests, [])

    def test_a_service_that_is_down_is_counted_and_never_blocks(self):
        net = FakeNet()
        net.fail = urllib.error.URLError("no route")
        a, _ = make(net=net)
        a.start()
        self.addCleanup(a.stop)
        for kind in ("estop", "camera", "power"):
            a.notify(kind, "x")
        self.assertTrue(wait_for(lambda: a.failed == 3))
        self.assertEqual(a.sent, 0)

    def test_stop_waits_for_the_last_message_to_go_out(self):
        a, net = make()
        a.start()
        a.notify("power", "goodbye", force=True)
        a.stop(wait=3)
        self.assertTrue(any(body == "goodbye" for _, body, _ in net.requests))

    def test_a_bad_address_is_refused_and_nothing_is_sent_anywhere(self):
        a, net = make(hb="not a url", ntfy="ftp://x/y")
        self.assertFalse(a.enabled)
        self.assertIn("isn't a web address", a.describe())
        a.start()
        self.assertEqual(net.requests, [])


class HeartbeatTests(unittest.TestCase):
    def test_the_heartbeat_carries_the_vital_signs(self):
        a, net = make()
        a.beat()
        url, body, _ = net.requests[0]
        self.assertEqual(url, HB)
        self.assertIn("Bob alive", body)
        self.assertIn("45 C", body)
        self.assertIsNotNone(a.last_beat)

    def test_a_failed_heartbeat_is_remembered_and_does_not_raise(self):
        net = FakeNet()
        net.fail = OSError("down")
        a, _ = make(net=net)
        a.beat()
        self.assertIsNone(a.last_beat)
        self.assertIn("down", a.describe())

    def test_overheating_weak_power_and_low_memory_notify_once_an_hour(self):
        clock = Clock()
        bad = {"load": 3.0, "mem_mb": 90, "temp_c": 83.0, "throttled": 0x50005, "disk_gb": 0.5}
        a, _ = make(clock=clock, sample=lambda base: bad)
        a.beat()
        queued = a._queue.qsize()
        self.assertEqual(queued, 4)                                     # hot, power, disk, memory
        a.beat()
        self.assertEqual(a._queue.qsize(), queued)                      # not again straight away
        clock.t += 3601
        a.beat()
        self.assertGreater(a._queue.qsize(), queued)

    def test_healthy_numbers_raise_nothing(self):
        self.assertEqual(problems({"temp_c": 50.0, "throttled": 0, "disk_gb": 9.0, "mem_mb": 1500}), [])
        self.assertEqual(problems({"throttled": 0x50000}), [])           # past events (bits 16+) are not a current problem

    def test_vitals_read_from_pretend_system_files(self):
        files = {"/proc/loadavg": "0.50 0.4 0.3 1/200 1234", "/proc/meminfo": "MemAvailable:    2048000 kB\n"}
        v = vitals(".", run=lambda args: "temp=51.2'C" if args[1] == "measure_temp" else "throttled=0x0", read=files.get)
        self.assertEqual((v["load"], v["mem_mb"], v["temp_c"], v["throttled"]), (0.5, 2000, 51.2, 0))
        self.assertIn("51 C", vitals_line(v))

    def test_describe_never_shows_the_secret_part_of_an_address(self):
        a, _ = make()
        text = a.describe()
        self.assertIn("hc-ping.com", text)
        self.assertNotIn("secret", text)


class RunningFlagTests(unittest.TestCase):
    def test_a_missing_clear_means_the_last_run_ended_badly(self):
        with tempfile.TemporaryDirectory() as d:
            flag = Path(d) / ".bob-running"
            self.assertFalse(mark_running(flag))        # first ever start
            self.assertTrue(mark_running(flag))         # the last run never cleared it: a crash, freeze or power cut
            clear_running(flag)
            self.assertFalse(mark_running(flag))        # after a clean stop


class ThroughTheRobot(unittest.TestCase):
    def setUp(self):
        import bob
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        cfg = config.Config()
        cfg.stream.enabled = False
        cfg.alerts.enabled = True
        self.ctrl = bob.Controller(cfg, sim=True, paused=True)
        self.addCleanup(self.ctrl.shutdown)
        self.net = FakeNet()
        self.ctrl.alerts = Alerts(cfg.alerts, "Bob", HB, NTFY, opener=self.net)
        self.ctrl.alerts.start()
        self.addCleanup(self.ctrl.alerts.stop)

    def test_an_emergency_stop_sends_a_high_priority_message(self):
        self.ctrl.estop("shared console: kai")
        self.assertTrue(wait_for(lambda: any(u == NTFY and "kai" in b for u, b, _ in self.net.requests)))

    def test_alerts_command_and_test_message(self):
        self.assertIn("heartbeat", self.ctrl.handle("/alerts"))
        self.assertIn("queued", self.ctrl.handle("/alerts test"))
        self.assertTrue(wait_for(lambda: any("alerts are working" in b for _, b, _ in self.net.requests)))
        self.assertIn("only the owner or an operator", self.ctrl.handle("/alerts test", by="v", role="viewer"))

    def test_claude_cannot_send_alerts(self):
        self.assertFalse({t["name"] for t in self.ctrl.brain.tools if "alert" in t["name"] or "notify" in t["name"]})


if __name__ == "__main__":
    unittest.main()
