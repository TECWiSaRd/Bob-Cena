import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from usage import UsageLedger  # noqa: E402


class Day:
    d = date(2026, 10, 22)

    def __call__(self):
        return self.d


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "usage.json"
        self.day, self.clock = Day(), Clock()

    def ledger(self):
        return UsageLedger(self.path, today=self.day, clock=self.clock)

    def test_it_adds_up_calls_tokens_and_cost_per_day_and_model(self):
        u = self.ledger()
        u.record("claude-sonnet-5-5", 1000, 200, 0, 800, 0.01)
        u.record("claude-sonnet-5-5", 500, 100, 300, 0, 0.02)
        u.record("claude-haiku-5-5", 100, 10, 0, 0, 0.001)
        t = u.total()
        self.assertEqual((t["calls"], t["input"], t["output"], t["cache_write"], t["cache_read"]), (3, 1600, 310, 300, 800))
        self.assertAlmostEqual(t["cost"], 0.031)
        self.assertEqual(u.by_model()["claude-sonnet-5-5"]["calls"], 2)

    def test_it_survives_a_restart_and_keeps_counting(self):
        u = self.ledger()
        u.record("claude-sonnet-5-5", 100, 10, 0, 0, 0.5)
        u.flush()
        again = self.ledger()
        again.record("claude-sonnet-5-5", 100, 10, 0, 0, 0.25)
        self.assertAlmostEqual(again.total()["cost"], 0.75)
        self.assertEqual(again.since, "2026-10-22")

    def test_periods(self):
        u = self.ledger()
        for offset, cost in ((0, 1.0), (3, 2.0), (6, 4.0), (7, 8.0), (40, 16.0)):
            self.day.d = date.fromordinal(date(2026, 10, 22).toordinal() - offset)
            u.record("claude-sonnet-5-5", 1, 1, 0, 0, cost)
        self.day.d = date(2026, 10, 22)
        report = u.report(0.123)
        row = {line.split()[0] + (" " + line.split()[1] if line.split()[1] in ("7", "time") else ""): line
               for line in report.splitlines() if line.startswith("  ") and "$" in line and "calls" not in line}
        self.assertIn("$1.00", row["today"])
        self.assertIn("$7.00", row["last 7"])                      # today, 3 and 6 days ago; not 7 days ago
        self.assertIn("$31.00", row["all time"])
        self.assertIn("this run: $0.123", report)

    def test_this_month_starts_on_the_first(self):
        u = self.ledger()
        self.day.d = date(2026, 9, 30)
        u.record("m", 1, 1, 0, 0, 5.0)
        self.day.d = date(2026, 10, 1)
        u.record("m", 1, 1, 0, 0, 2.0)
        self.day.d = date(2026, 10, 22)
        self.assertIn("$2.00", [l for l in u.report().splitlines() if l.strip().startswith("this month")][0])

    def test_saving_is_throttled_but_flush_always_writes(self):
        u = self.ledger()
        u.record("m", 1, 1, 0, 0, 1.0)
        self.assertFalse(self.path.exists())                       # not yet: it spares the SD card
        self.clock.t += 31
        u.record("m", 1, 1, 0, 0, 1.0)
        self.assertTrue(self.path.exists())
        u.record("m", 1, 1, 0, 0, 1.0)
        u.flush()
        self.assertEqual(json.loads(self.path.read_text())["days"]["2026-10-22"]["m"]["calls"], 3)

    def test_a_corrupt_file_is_kept_aside_and_counting_starts_again(self):
        self.path.write_text("{ not json")
        u = self.ledger()
        self.assertEqual(u.total()["calls"], 0)
        self.assertTrue(self.path.with_name("usage.json.bad").exists())
        u.record("m", 1, 1, 0, 0, 1.0)
        u.flush()
        self.assertEqual(self.ledger().total()["calls"], 1)

    def test_a_file_with_missing_fields_still_loads(self):
        self.path.write_text(json.dumps({"days": {"2026-10-20": {"m": {"calls": 2, "cost": 1.5}}}}))
        u = self.ledger()
        self.assertEqual(u.total()["calls"], 2)
        self.assertAlmostEqual(u.total()["cost"], 1.5)

    def test_an_empty_ledger_reports_cleanly(self):
        report = self.ledger().report()
        self.assertIn("all time", report)
        self.assertIn("$0.00", report)


class ThroughTheRobot(unittest.TestCase):
    def setUp(self):
        import bob
        import config
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        cfg = config.Config()
        cfg.stream.enabled = False
        self.ctrl = bob.Controller(cfg, sim=True, paused=True)
        self.addCleanup(self.ctrl.shutdown)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctrl.controls.usage = UsageLedger(Path(self.tmp.name) / "u.json")

    def test_every_thought_is_counted_and_shown_by_the_usage_command(self):
        usage = SimpleNamespace(input_tokens=2000, output_tokens=100, cache_creation_input_tokens=0, cache_read_input_tokens=1000)
        self.ctrl.brain.cfg.model = "claude-sonnet-5-5"
        self.ctrl.brain._account(usage)
        self.ctrl.brain._account(usage)
        text = self.ctrl.handle("/usage")
        self.assertIn("all time", text)
        self.assertIn("claude-sonnet-5-5", text)
        self.assertIn("2 calls", text)
        expected = 2 * (2000 * 2.00 + 100 * 10.00 + 1000 * 0.20) / 1e6
        self.assertAlmostEqual(self.ctrl.controls.usage.total()["cost"], expected)
        self.assertAlmostEqual(self.ctrl.controls.cost, expected)             # and the running status-bar figure agrees
        self.assertEqual(self.ctrl.handle("/cost"), text)                       # /cost is the same command

    def test_shutdown_saves_the_ledger(self):
        usage = SimpleNamespace(input_tokens=10, output_tokens=1, cache_creation_input_tokens=None, cache_read_input_tokens=None)
        self.ctrl.brain._account(usage)
        self.ctrl.shutdown()
        self.assertTrue((Path(self.tmp.name) / "u.json").exists())


if __name__ == "__main__":
    unittest.main()
