"""Checks for /check, the event timeline and /find. No hardware needed. Run:  python3 -m unittest discover -s tests"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import selfcheck  # noqa: E402
from timeline import Timeline  # noqa: E402
from vision import Face, Follower  # noqa: E402


class FakeClock:
    def __init__(self):
        self.t = time.time()

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += max(s, 0.001)


class TimelineTests(unittest.TestCase):
    def make(self, **kw):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        cfg = config.TimelineConfig(enabled=True, thumbnails=False, **kw)
        clock = FakeClock()
        return Timeline(cfg, Path(d.name) / "tl", clock), clock

    def test_disabled_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            tl = Timeline(config.TimelineConfig(), Path(d) / "tl")
            tl.record("tick", n=1)
            self.assertFalse((Path(d) / "tl").exists())

    def test_records_and_reads_back_in_order(self):
        tl, clock = self.make()
        for i in range(5):
            clock.t += 1
            tl.record("tool", name="drive", n=i)
        rows = tl.recent(3)
        self.assertEqual([r["n"] for r in rows], [2, 3, 4])
        self.assertIn("drive", tl.format(rows[0]))

    def test_long_text_is_trimmed(self):
        tl, _ = self.make()
        tl.record("operator", text="x" * 5000)
        self.assertLessEqual(len(tl.recent(1)[0]["text"]), 200)

    def test_old_files_deleted(self):
        tl, clock = self.make(keep_days=1.0)
        tl.record("tick", n=1)
        first = next(tl.dir.glob("*.jsonl"))
        clock.t += 3 * 86400        # three days later: the first day's file is now old
        tl._last_prune = clock.t    # hold off the automatic cleanup until the file times are set below
        tl.record("tick", n=2)
        for p in tl.dir.glob("*.jsonl"):   # file times come from the real clock, so set them to match the fake one
            t = clock.t - (3 * 86400 if p == first else 0)
            os.utime(p, (t, t))
        tl._prune(force=True)
        self.assertEqual(sum(1 for _ in tl.dir.glob("*.jsonl")), 1)
        self.assertEqual([r["n"] for r in tl.recent(5)], [2])

    def test_size_cap_removes_oldest(self):
        tl, clock = self.make(max_mb=1)
        thumbs = tl.dir / "thumbs"
        thumbs.mkdir(parents=True)
        for i in range(4):
            p = thumbs / f"{i}.jpg"
            p.write_bytes(b"x" * 400_000)
            os.utime(p, (clock.t - 100 + i, clock.t - 100 + i))
        tl._prune(force=True)
        left = sorted(p.name for p in thumbs.iterdir())
        self.assertEqual(left, ["2.jpg", "3.jpg"])

    def test_clear_deletes_everything(self):
        tl, _ = self.make()
        tl.record("tick", n=1)
        self.assertGreaterEqual(tl.clear(), 1)
        self.assertEqual(tl.recent(5), [])

    def test_unwritable_folder_does_not_raise(self):
        with tempfile.TemporaryDirectory() as d:
            blocker = Path(d) / "tl"
            blocker.write_text("a file where the folder should be")
            tl = Timeline(config.TimelineConfig(enabled=True), blocker)
            tl.record("tick", n=1)    # must not raise


    def test_thumbnails_never_overwrite_each_other(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        tl = Timeline(config.TimelineConfig(enabled=True, thumb_every_s=0.0), Path(d.name) / "tl", lambda: 1_700_000_000.123)
        tl._shrink = lambda jpeg: jpeg
        names = {tl.thumbnail(bytes([i]) * 10) for i in range(5)}    # five pictures in the same millisecond
        self.assertEqual(len(names), 5)
        self.assertEqual(len(list((tl.dir / "thumbs").iterdir())), 5)


class FakeDrive:
    def __init__(self):
        self.estop = threading.Event()
        self.moves = []

    def start(self, left, right, seconds):
        self.moves.append((left, right))

    def stop(self):
        self.moves.append("stop")


class FakeCamera:
    def grab_bgr(self):
        return object()


class FakeDetector:
    name = "fake"

    def __init__(self, face_after_looks):
        self.looks = 0
        self.after = face_after_looks

    def detect(self, frame):
        self.looks += 1
        return [Face(0.7, 0.5, 0.1, 0.2)] if self.looks >= self.after else []


class FindTests(unittest.TestCase):
    def make(self, face_after):
        clock = FakeClock()
        drive = FakeDrive()
        det = FakeDetector(face_after)
        f = Follower(config.FollowConfig(), 62.0, FakeCamera(), drive, None, lambda: det, clock=clock, sleep=clock.sleep)
        f._detector = det
        return f, drive, clock

    def run_find(self, f, seconds=20, allowed=lambda: True):
        f.active, f.found, f.mode = True, False, "find"
        f._stop.clear()
        f._scan(seconds, allowed)

    def test_finds_a_face_and_stops(self):
        f, drive, _ = self.make(face_after=3)
        self.run_find(f)
        self.assertTrue(f.found)
        self.assertEqual(drive.moves[-1], "stop")
        self.assertIn("right", f.result)
        self.assertFalse(f.active)

    def test_spins_in_place_never_forward(self):
        f, drive, _ = self.make(face_after=5)
        self.run_find(f)
        for m in drive.moves:
            if m != "stop":
                left, right = m
                self.assertAlmostEqual(left, -right)   # equal and opposite: a spin on the spot
                self.assertLessEqual(abs(left), 0.5)

    def test_gives_up_when_nobody_is_there(self):
        f, drive, clock = self.make(face_after=10_000)
        t0 = clock.t
        self.run_find(f, seconds=10)
        self.assertFalse(f.found)
        self.assertIn("saw no face", f.result)
        self.assertLess(clock.t - t0, 12)
        self.assertEqual(drive.moves[-1], "stop")

    def test_emergency_stop_ends_it(self):
        f, drive, _ = self.make(face_after=10_000)
        drive.estop.set()
        self.run_find(f)
        self.assertIn("emergency stop", f.result)
        self.assertNotIn((0.35, -0.35), drive.moves)

    def test_each_session_keeps_its_own_outcome(self):
        f, drive, _ = self.make(face_after=2)
        f.session = 1
        self.run_find(f)
        first = f.outcome(1, 1)
        self.assertTrue(first[0])
        f.session = 2                      # a later session that finds nobody must not rewrite session 1
        f._detector.after = 10_000
        self.run_find(f, seconds=5)
        self.assertTrue(f.outcome(1, 1)[0])
        self.assertFalse(f.outcome(2, 1)[0])
        self.assertIsNone(f.outcome(99, 0))

    def test_operator_pause_ends_it(self):
        f, drive, _ = self.make(face_after=10_000)
        self.run_find(f, allowed=lambda: False)
        self.assertIn("paused", f.result)


class OperatorCommands(unittest.TestCase):
    """The timeline must show what the operator did, not only what Claude did."""

    def setUp(self):
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        import bob
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        cfg = config.Config()
        cfg.stream.enabled = False
        self.ctrl = bob.Controller(cfg, sim=True, paused=True)
        self.ctrl.timeline = Timeline(config.TimelineConfig(enabled=True, thumbnails=False), Path(self.d.name) / "tl")
        self.addCleanup(self.ctrl.shutdown)

    def events(self, kind):
        return [r for r in self.ctrl.timeline.recent(100) if r["kind"] == kind]

    def test_slash_commands_are_recorded(self):
        for line in ("/speed 0.4", "/motion off", "/pause", "/range off", "/fwd 0.1", "/move 0.3 0.3 0.1", "/find off"):
            self.ctrl.handle(line)
        got = {(r["cmd"], r.get("arg")) for r in self.events("operator_command")}
        self.assertIn(("speed", "0.4"), got)
        self.assertIn(("motion", "off"), got)
        self.assertIn(("pause", None), got)
        self.assertIn(("range", "off"), got)
        self.assertIn(("fwd", "0.1"), got)
        self.assertIn(("move", "0.3 0.3 0.1"), got)
        self.assertIn(("find", "off"), got)

    def test_ask_is_not_recorded_twice_and_timeline_commands_are_skipped(self):
        self.ctrl.handle("/ask hello")
        self.ctrl.handle("/timeline show")
        self.assertEqual([r["text"] for r in self.events("operator")], ["hello"])
        self.assertEqual(self.events("operator_command"), [])

    def test_held_keys_are_one_event_per_burst(self):
        for _ in range(20):
            self.ctrl.manual(0.5, 0.5, 0.1)
        self.assertEqual(len(self.events("manual_move")), 1)


class FakeCtrl:
    def __init__(self):
        self.cfg = config.Config()
        self.drive = SimpleNamespace(sim=False, estop=threading.Event(), speed_cap=0.8)
        self.camera = SimpleNamespace(available=True, enabled=True, capture_jpeg=lambda: b"x" * 4096)
        self.audio = SimpleNamespace(sim=False, muted=False, _engines=["piper"])
        self.listener = SimpleNamespace(on=False)
        self.ranger = SimpleNamespace()
        self.stream = None
        self.music = None
        self.radio = None
        self.controls = SimpleNamespace(auto=True)
        self.timeline = None


class CheckTests(unittest.TestCase):
    def run_checks(self, ctrl, thr="throttled=0x0", link="signal: -55 dBm", temp="48000", mem="MemAvailable: 900000 kB"):
        def run(args, timeout=3):
            return {"vcgencmd": thr, "iw": link if "link" in args else "Power save: off"}.get(args[0])

        def read(path):
            return temp if "thermal" in path else mem

        os.environ["ANTHROPIC_API_KEY"] = "k"
        return {name: (lv, d) for lv, name, d in selfcheck.run_checks(ctrl, Path("."), run, read, lambda x: "/usr/bin/" + x)}

    def test_healthy_pi(self):
        r = self.run_checks(FakeCtrl())
        for name in ("motors", "camera", "speaker", "claude", "temperature", "power", "wi-fi"):
            self.assertEqual(r[name][0], "ok", (name, r[name]))

    def test_problems_are_flagged(self):
        c = FakeCtrl()
        c.camera.available = False
        c.drive.sim = True
        r = self.run_checks(c, thr="throttled=0x50005", link="signal: -82 dBm", temp="83000")
        self.assertEqual(r["camera"][0], "FAIL")
        self.assertEqual(r["motors"][0], "WARN")
        self.assertEqual(r["power"][0], "WARN")
        self.assertIn("under-voltage", r["power"][1])
        self.assertEqual(r["wi-fi"][0], "WARN")
        self.assertEqual(r["temperature"][0], "FAIL")

    def test_estop_and_mute_and_missing_key(self):
        c = FakeCtrl()
        c.drive.estop.set()
        c.audio.muted = True
        r = self.run_checks(c)
        self.assertEqual(r["motors"][0], "WARN")
        self.assertEqual(r["speaker"][0], "WARN")
        os.environ.pop("ANTHROPIC_API_KEY")
        out = {n: lv for lv, n, _ in selfcheck.run_checks(c, Path("."), lambda *a, **k: None, lambda p: None, lambda x: x)}
        self.assertEqual(out["claude"], "FAIL")

    def test_report_summary(self):
        text = selfcheck.format_report([("ok", "a", "fine"), ("FAIL", "b", "broken"), ("WARN", "c", "meh")])
        self.assertIn("1 ok, 1 warning, 1 problem", text)
        self.assertIn("needs attention", text)


if __name__ == "__main__":
    unittest.main()
