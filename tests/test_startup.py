import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from startup import Stagger, cpu_busy_percent  # noqa: E402


class FakeTime:
    def __init__(self):
        self.t = 0.0

    def clock(self):
        return self.t

    def sleep(self, s):
        self.t += s


def make(busy_values, **cfg):
    ft = FakeTime()
    readings = iter(busy_values)
    last = [0.0]

    def busy():
        try:
            last[0] = next(readings)
        except StopIteration:
            pass
        ft.t += 0.5
        return last[0]

    stagger = Stagger(config.StartupConfig(**cfg), busy=busy, clock=ft.clock, sleep=ft.sleep)
    return stagger, ft


class StaggerTests(unittest.TestCase):
    def test_parts_start_in_order_and_only_when_the_cpu_is_calm(self):
        order, times = [], []
        stagger, ft = make([95, 90, 80, 30, 20, 95, 20, 20, 20, 20, 20, 20])
        steps = [(n, (lambda n=n: (order.append(n), times.append(ft.t)))) for n in ("voice", "index", "microphone")]
        stagger.run(steps)
        self.assertEqual(order, ["voice", "index", "microphone"])
        self.assertGreater(times[0], 1.5)                       # it waited while the CPU was at 95%, 90%, 80%
        self.assertTrue(stagger.done)

    def test_it_gives_up_waiting_after_the_time_limit(self):
        order = []
        stagger, ft = make([99] * 500, max_wait_s=5.0, step_pause_s=1.0)
        stagger.run([("a", lambda: order.append("a")), ("b", lambda: order.append("b"))])
        self.assertEqual(order, ["a", "b"])                     # a busy Pi doesn't block Bob from starting for ever
        self.assertLess(ft.t, 20)

    def test_a_failing_part_does_not_stop_the_rest(self):
        order = []

        def boom():
            raise RuntimeError("no radio hardware")

        stagger, _ = make([10] * 50)
        stagger.run([("radio", boom), ("microphone", lambda: order.append("mic"))])
        self.assertEqual(order, ["mic"])
        self.assertEqual(stagger.started, ["microphone"])

    def test_shutdown_stops_the_remaining_parts_from_starting(self):
        order, halt = [], []
        ft = FakeTime()
        stagger = Stagger(config.StartupConfig(), stop=lambda: bool(halt), busy=lambda: 10.0, clock=ft.clock, sleep=ft.sleep)
        stagger.run([("a", lambda: (order.append("a"), halt.append(1))), ("b", lambda: order.append("b"))])
        self.assertEqual(order, ["a"])

    def test_where_the_cpu_cannot_be_measured_it_just_pauses_between_parts(self):
        order = []
        ft = FakeTime()
        stagger = Stagger(config.StartupConfig(step_pause_s=3.0), busy=lambda: None, clock=ft.clock, sleep=ft.sleep)
        stagger.run([("a", lambda: order.append("a")), ("b", lambda: order.append("b"))])
        self.assertEqual(order, ["a", "b"])
        self.assertGreaterEqual(ft.t, 6.0)

    def test_cpu_reading_from_proc_stat_numbers(self):
        samples = iter([(1000, 900), (1100, 920)])               # 100 ticks passed, 20 of them idle: 80% busy
        self.assertAlmostEqual(cpu_busy_percent(0.0, read=lambda: next(samples), sleep=lambda s: None), 80.0)
        self.assertIsNone(cpu_busy_percent(0.0, read=lambda: (_ for _ in ()).throw(OSError()), sleep=lambda s: None))


class ThroughTheRobot(unittest.TestCase):
    def setUp(self):
        import bob
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        self.bob = bob

    def robot(self, stagger):
        cfg = config.Config()
        cfg.stream.enabled = False
        cfg.startup.stagger = stagger
        cfg.startup.step_pause_s = 0.0
        ctrl = self.bob.Controller(cfg, sim=True, paused=True)
        self.addCleanup(ctrl.shutdown)
        self.started = []
        ctrl.brain.start = lambda: self.started.append("brain")
        ctrl.listener.start = lambda: self.started.append("mic")
        ctrl.index.start = lambda: self.started.append("index")
        return ctrl

    def test_staggered_start_returns_at_once_and_brings_everything_up_in_the_background(self):
        ctrl = self.robot(True)
        ctrl.start()
        self.assertIsNotNone(ctrl.stagger)
        end = time.monotonic() + 15
        while not ctrl.stagger.done and time.monotonic() < end:
            time.sleep(0.05)
        self.assertTrue(ctrl.stagger.done)
        self.assertEqual(self.started[0], "brain")
        self.assertEqual(self.started[-1], "mic")                # the heaviest part is last
        self.assertIn("index", self.started)

    def test_with_staggering_off_everything_starts_immediately_as_before(self):
        ctrl = self.robot(False)
        ctrl.start()
        self.assertEqual(sorted(self.started), ["brain", "index", "mic"])
        self.assertIsNone(ctrl.stagger)

    def test_the_voice_is_not_loaded_in_the_constructor_when_staggering(self):
        cfg = config.Config()
        cfg.stream.enabled = False
        ctrl = self.bob.Controller(cfg, sim=True, paused=True)
        self.addCleanup(ctrl.shutdown)
        self.assertFalse(getattr(ctrl.audio, "_warming", False))


if __name__ == "__main__":
    unittest.main()
