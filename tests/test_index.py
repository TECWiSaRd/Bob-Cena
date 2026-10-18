"""Checks for the search index. No hardware needed. Run:  python3 -m unittest discover -s tests"""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from index import Index, fts_expression, parse_query, parse_since  # noqa: E402


def iso(ts):
    return datetime.fromtimestamp(ts).isoformat(timespec="milliseconds")


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.base = Path(self.d.name)
        (self.base / "logs" / "timeline").mkdir(parents=True)
        (self.base / "manuals").mkdir()
        self.now = time.time()
        self.cfg = config.IndexConfig()
        self.ix = Index(self.cfg, self.base, lambda: self.now)

    def event(self, kind, day="2026-10-16", offset=0.0, **data):
        row = {"t": iso(self.now + offset), "kind": kind, **data}
        with open(self.base / "logs" / "timeline" / f"{day}.jsonl", "a") as f:
            f.write(json.dumps(row) + "\n")

    def found(self, query, **kw):
        return [h["body"] for h in self.ix.search(query, **kw)]

    def test_finds_timeline_events_by_word_and_kind(self):
        self.event("estop", source="dashboard")
        self.event("tool", name="drive", result="BLOCKED: motion off")
        self.assertEqual(len(self.found("dashboard")), 1)
        self.assertEqual(len(self.found("kind:tool")), 1)
        self.assertEqual(len(self.found("blocked motion")), 1)      # every word must match, in any order
        self.assertEqual(self.found("nonexistent"), [])

    def test_prefix_and_plural_matching(self):
        self.event("operator", text="the lens is covered")
        self.assertTrue(self.found("cover"))
        self.assertTrue(self.found("lens"))

    def test_incremental_no_duplicates(self):
        self.event("tick", n=1)
        self.ix.sync()
        self.ix.sync()
        self.event("tick", n=2)
        self.ix.sync()
        self.assertEqual(len(self.ix.search("kind:tick")), 2)

    def test_half_written_line_waits_for_its_newline(self):
        path = self.base / "logs" / "timeline" / "2026-10-16.jsonl"
        line = json.dumps({"t": iso(self.now), "kind": "tick", "n": 7})
        path.write_text(line[:20])
        self.assertEqual(self.ix.search("kind:tick"), [])
        path.write_text(line + "\n")
        self.assertEqual(len(self.ix.search("kind:tick")), 1)

    def test_deleted_timeline_file_removes_its_rows(self):
        self.event("estop", day="2026-10-15")
        self.event("estop", day="2026-10-16")
        self.assertEqual(len(self.ix.search("kind:estop")), 2)
        (self.base / "logs" / "timeline" / "2026-10-15.jsonl").unlink()
        self.assertEqual(len(self.ix.search("kind:estop")), 1)

    def test_forget_removes_timeline_rows_immediately(self):
        self.event("estop")
        self.ix.sync()
        self.ix.forget("timeline")
        (self.base / "logs" / "timeline" / "2026-10-16.jsonl").unlink()
        self.assertEqual(self.ix.search("kind:estop"), [])

    def test_since_filter(self):
        self.event("tick", offset=-3 * 86400, n=1)
        self.event("tick", offset=-60, n=2)
        self.assertEqual(len(self.ix.search("kind:tick")), 2)
        self.assertEqual(len(self.ix.search("kind:tick since:1d")), 1)

    def test_notes_and_people_mirror_and_follow_edits(self):
        (self.base / "memory.json").write_text(json.dumps(["Sam likes robots", "the hallway is slippery"]))
        (self.base / "people.json").write_text(json.dumps({"Sam": {"description": "red cap", "notes": "tall", "seen": "x"}}))
        self.assertEqual(len(self.ix.search("source:note")), 2)
        self.assertEqual(len(self.ix.search("red cap")), 1)
        time.sleep(0.02)
        (self.base / "memory.json").write_text(json.dumps(["the hallway is slippery"]))
        os.utime(self.base / "memory.json", (self.now + 5, self.now + 5))
        self.assertEqual(len(self.ix.search("source:note")), 1)
        (self.base / "people.json").write_text("{}")
        os.utime(self.base / "people.json", (self.now + 9, self.now + 9))
        self.assertEqual(self.ix.search("red cap"), [])

    def test_damaged_json_files_do_not_break_the_index(self):
        (self.base / "memory.json").write_text("[not json")
        self.event("tick", n=1)
        self.assertEqual(len(self.ix.search("kind:tick")), 1)
        self.assertEqual(self.ix.last_error, "")

    def test_radio_and_log_and_manuals(self):
        (self.base / "logs" / "radio.jsonl").write_text(json.dumps({"ts": self.now, "from": "John", "to": "Bob", "text": "hello brother"}) + "\n")
        (self.base / "logs" / "bob.log").write_text("12:00:00 INFO  fine\n12:00:01 WARNING Camera unplugged\n   continuation\n")
        (self.base / "manuals" / "06-calibration.md").write_text("# Calibration\n\n## Turning\nSpin the robot slowly.\n")
        self.assertEqual(len(self.ix.search("brother")), 1)
        self.assertEqual(len(self.ix.search("camera unplugged")), 1)
        self.assertEqual(self.ix.search("fine"), [])                      # only warnings and errors from the log
        hit = self.ix.search("spin slowly source:manual")
        self.assertEqual(len(hit), 1)
        self.assertIn("Turning", hit[0]["body"])

    def test_rotated_log_is_read_again_from_the_top(self):
        log = self.base / "logs" / "bob.log"
        log.write_text("12:00:00 WARNING first problem is here\n" * 3)
        self.ix.sync()
        log.write_text("12:05:00 ERROR second\n")            # smaller than before: the file was rotated
        self.assertEqual(len(self.ix.search("second")), 1)

    def test_claude_sees_only_history(self):
        (self.base / "memory.json").write_text(json.dumps(["secret note"]))
        (self.base / "manuals" / "a.md").write_text("# Secret\nsecret manual text")
        (self.base / "logs" / "bob.log").write_text("12:00:00 ERROR secret failure\n")
        self.event("tool", name="look", result="a secret door")
        lines = self.ix.recall("secret")
        self.assertEqual(len(lines), 1)
        self.assertIn("door", lines[0])
        self.assertEqual(len(self.ix.search("secret")), 4)    # the operator sees all four

    def test_recall_caps_results_and_trims_lines(self):
        for i in range(20):
            self.event("operator", text="word " + "x" * 500, n=i)
        lines = self.ix.recall("word")
        self.assertEqual(len(lines), 5)
        self.assertTrue(all(len(line) < 260 for line in lines))

    def test_hostile_queries_are_harmless(self):
        self.event("tick", n=1)
        for q in ('"; DROP TABLE docs; --', "* OR 1=1", "a:b:c", "NEAR(", "'", ""):
            self.ix.search(q)             # must not raise or damage anything
        self.assertEqual(len(self.ix.search("kind:tick")), 1)

    def test_bad_since_is_explained(self):
        with self.assertRaisesRegex(ValueError, "since"):
            self.ix.search("since:someday")

    def test_damaged_database_is_rebuilt_from_the_files(self):
        self.event("estop")
        self.ix.sync()
        self.ix.path.write_bytes(b"this is not a database at all" * 100)
        self.assertEqual(len(self.ix.search("kind:estop")), 1)

    def test_locked_database_is_never_wiped(self):
        self.event("estop")
        self.ix.sync()
        blocker = sqlite3.connect(self.ix.path)
        blocker.execute("BEGIN EXCLUSIVE")
        try:
            self.event("estop", offset=1)          # something new to write, so a write is attempted
            self.ix.timeout = 0.1
            self.ix.sync()
            self.assertIn("locked", self.ix.last_error)
        finally:
            blocker.rollback()
            blocker.close()
        self.ix.timeout = 5.0
        self.assertEqual(len(self.ix.search("kind:estop")), 2)    # the old row survived, and the new one arrived

    def test_disabled_index_does_nothing(self):
        ix = Index(config.IndexConfig(enabled=False), self.base)
        ix.sync()
        self.assertEqual(ix.search("anything"), [])
        self.assertFalse(ix.path.exists())

    def test_row_cap_drops_oldest_history_but_not_notes(self):
        small = Index(config.IndexConfig(max_rows=5), self.base, lambda: self.now)
        (self.base / "memory.json").write_text(json.dumps(["keep me"]))
        for i in range(10):
            self.event("tick", offset=i, n=i)
        small.sync()
        self.assertEqual(len(small.search("source:note")), 1)
        self.assertEqual(len(small.search("kind:tick", 50)), 4)

    def test_status_text(self):
        self.event("tick", n=1)
        self.ix.sync()
        self.assertIn("1 timeline", self.ix.status())


class HelperTests(unittest.TestCase):
    def test_parse_since(self):
        now = time.time()
        self.assertAlmostEqual(parse_since("2h", now), now - 7200)
        self.assertAlmostEqual(parse_since("30m", now), now - 1800)
        self.assertLess(parse_since("yesterday", now), parse_since("today", now))
        self.assertIsNone(parse_since("soon", now))
        self.assertIsNotNone(parse_since("2026-10-16", now))

    def test_parse_query(self):
        text, f = parse_query("lens covered kind:ESTOP source:timeline since:1d", time.time())
        self.assertEqual(text, "lens covered")
        self.assertEqual((f["kind"], f["source"]), ("estop", "timeline"))
        self.assertIn("since", f)

    def test_fts_expression_is_safe(self):
        self.assertEqual(fts_expression('he said "hi" -- OR'), '"he"* "said"* "hi"* "or"*')
        self.assertEqual(fts_expression("***"), "")


if __name__ == "__main__":
    unittest.main()
