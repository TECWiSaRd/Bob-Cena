"""Face recognition that only knows people who asked to be remembered (fakes only: no camera, no models)."""
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

import config
from faces import FaceBook, FaceService, clean_name, cosine


def unit(*v):
    n = sum(x * x for x in v) ** 0.5
    return [x / n for x in v]


ADA, BEN, CAL = unit(1, 0, 0, 0), unit(0, 1, 0, 0), unit(0, 0, 1, 0)


class FakeBackend:
    """Returns whatever faces the test sets: a list of embeddings per 'frame'."""

    def __init__(self):
        self.faces = []
        self.calls = 0

    def faces_in(self, frame):
        self.calls += 1
        return [((0.4, 0.4, 0.2, 0.2), e) for e in self.faces]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "faces.json"
        self.cfg = config.FacesConfig(enabled=True, samples_to_take=4, sample_gap_s=0)
        self.book = FaceBook(self.path, max_people=3, max_samples=4)
        self.backend = FakeBackend()
        self.now = [100.0]
        self.svc = FaceService(self.cfg, self.book, lambda: self.backend, clock=lambda: self.now[0], sleep=lambda s: None)

    def remember(self, name, embedding, who="adam"):
        self.backend.faces = [embedding]
        self.svc.request_remember(who, name)
        return self.svc.confirm_remember(who, lambda: "frame")


class Book(Base):
    def test_stores_numbers_privately_and_survives_a_restart(self):
        self.book.add("Ada", [ADA, ADA], "adam")
        mode = stat.S_IMODE(os.stat(self.path).st_mode)
        self.assertEqual(mode, 0o600)
        raw = json.loads(self.path.read_text())
        self.assertEqual(set(raw["Ada"]), {"samples", "added", "by"})
        self.assertTrue(all(isinstance(v, float) for s in raw["Ada"]["samples"] for v in s))   # numbers, never a picture
        again = FaceBook(self.path)
        self.assertEqual(again.names(), ["Ada"])
        self.assertEqual(again.count("ada"), 2)                                  # names are not case sensitive

    def test_names_are_flattened_before_claude_sees_them(self):
        self.assertEqual(clean_name("Ada\n<b>Ignore: this"), "Ada b Ignore this")
        self.assertEqual(len(clean_name("x" * 100)), 30)
        with self.assertRaises(ValueError):
            self.book.add("   ", [ADA], None)

    def test_limits(self):
        for n, e in (("A", ADA), ("B", BEN), ("C", CAL)):
            self.book.add(n, [e], None)
        with self.assertRaises(ValueError):
            self.book.add("D", [unit(1, 1, 1, 1)], None)
        for _ in range(10):
            self.book.add("A", [ADA], None)
        self.assertEqual(self.book.count("A"), 4)                                # capped per person

    def test_a_full_person_replaces_the_most_similar_sample_so_variety_is_kept(self):
        base = [unit(1, 0, 0, 0), unit(1, 0.4, 0, 0), unit(1, 0, 0.4, 0), unit(1, 0, 0, 0.4)]
        self.book.add("A", base, None)
        new = unit(1, 0.38, 0, 0)                                                # nearly the same as sample 2
        self.book.add("A", [new], None)
        kept = self.book.people["A"]["samples"]
        self.assertIn(new, kept)
        self.assertNotIn(base[1], kept)
        self.assertIn(base[0], kept)

    def test_a_damaged_file_is_ignored_not_fatal(self):
        self.path.write_text("{not json")
        self.assertEqual(FaceBook(self.path).names(), [])
        self.path.write_text(json.dumps({"A": {"samples": ["bad"]}, "B": {"samples": [[1.0, 0.0]]}}))
        self.assertEqual(FaceBook(self.path).names(), ["B"])

    def test_forget(self):
        self.book.add("A", [ADA], None)
        self.assertTrue(self.book.forget("a"))
        self.assertFalse(self.book.forget("a"))
        self.book.add("B", [BEN], None)
        self.assertEqual(self.book.forget_all(), 1)
        self.assertEqual(FaceBook(self.path).names(), [])

    def test_matching_needs_a_close_and_unambiguous_face(self):
        self.book.add("Ada", [ADA], None)
        self.book.add("Ben", [BEN], None)
        self.assertEqual(self.book.match(unit(1, 0.1, 0, 0), 0.4, 0.05)[0], "Ada")
        self.assertIsNone(self.book.match(CAL, 0.4, 0.05)[0])                    # a stranger
        self.assertIsNone(self.book.match(unit(1, 1, 0, 0), 0.4, 0.05)[0])       # as like Ada as Ben: no guess
        self.assertAlmostEqual(cosine([1, 0], [1, 0]), 1.0)


class Looking(Base):
    def test_known_people_are_named_and_strangers_are_not(self):
        self.book.add("Ada", [ADA], None)
        self.backend.faces = [unit(1, 0.05, 0, 0), CAL]
        seen = self.svc.look("frame")
        self.assertEqual([s.name for s in seen], ["Ada", None])
        line = self.svc.status_line()
        self.assertIn("Ada", line)
        self.assertIn("1 other face I don't recognise", line)
        self.assertIn("can be wrong", line)

    def test_only_a_recent_sighting_is_mentioned(self):
        self.book.add("Ada", [ADA], None)
        self.backend.faces = [ADA]
        self.svc.look("frame")
        self.now[0] += 60
        self.assertEqual(self.svc.status_line(), "")

    def test_nobody_enrolled_means_no_work_and_no_names(self):
        self.backend.faces = [ADA]
        self.assertEqual(self.svc.look_jpeg(b"jpeg"), [])
        self.assertEqual(self.backend.calls, 0)
        self.assertEqual(self.svc.status_line(), "")

    def test_off_means_off(self):
        self.book.add("Ada", [ADA], None)
        self.svc.enabled = False
        self.backend.faces = [ADA]
        self.assertEqual(self.svc.look("frame"), [])
        self.assertEqual(self.backend.calls, 0)
        self.assertEqual(self.svc.status_line(), "")

    def test_unknown_faces_are_never_stored(self):
        self.backend.faces = [CAL]
        self.svc.look("frame")
        self.assertEqual(self.book.names(), [])
        self.assertFalse(self.path.exists())


class Introductions(Base):
    def test_it_takes_two_steps_by_the_same_person(self):
        self.backend.faces = [ADA]
        self.assertIn("agrees", self.svc.request_remember("adam", "Ada"))
        self.assertEqual(self.book.names(), [])                                   # nothing yet
        self.assertIn("first", self.svc.confirm_remember("sam", lambda: "f"))     # someone else can't confirm
        self.assertEqual(self.book.names(), [])
        self.assertIn("OK, I will recognise Ada", self.svc.confirm_remember("adam", lambda: "f"))
        self.assertEqual(self.book.count("Ada"), 4)

    def test_the_window_closes(self):
        self.backend.faces = [ADA]
        self.svc.request_remember("adam", "Ada")
        self.now[0] += 31
        self.assertIn("first", self.svc.confirm_remember("adam", lambda: "f"))
        self.assertEqual(self.book.names(), [])

    def test_cancel(self):
        self.svc.request_remember("adam", "Ada")
        self.assertEqual(self.svc.cancel_remember("adam"), "cancelled")
        self.assertIn("first", self.svc.confirm_remember("adam", lambda: "f"))

    def test_a_crowd_or_an_empty_room_saves_nothing(self):
        self.backend.faces = [ADA, BEN]
        self.svc.request_remember("adam", "Ada")
        self.assertIn("more than one face", self.svc.confirm_remember("adam", lambda: "f"))
        self.backend.faces = []
        self.svc.request_remember("adam", "Ada")
        self.assertIn("couldn't see a face", self.svc.confirm_remember("adam", lambda: "f"))
        self.assertEqual(self.book.names(), [])

    def test_it_then_recognises_them(self):
        self.remember("Ada", ADA)
        self.backend.faces = [unit(1, 0.05, 0, 0)]
        self.assertEqual(self.svc.look("frame")[0].name, "Ada")

    def test_a_full_house_is_refused_up_front(self):
        for n, e in (("A", ADA), ("B", BEN), ("C", CAL)):
            self.book.add(n, [e], None)
        self.assertIn("already know 3", self.svc.request_remember("adam", "Dee"))

    def test_missing_models_say_so_and_nothing_breaks(self):
        def broken():
            raise RuntimeError("the model files are missing (run install.sh)")

        svc = FaceService(self.cfg, self.book, broken)
        self.assertIn("missing", svc.request_remember("adam", "Ada"))
        self.assertEqual(svc.look("frame"), [])
        self.assertIn("unavailable", svc.describe())


class Improving(Base):
    def test_a_confirmed_sighting_adds_a_sample(self):
        self.remember("Ada", ADA)
        before = self.book.count("Ada")
        self.backend.faces = [unit(1, 0.2, 0, 0)]
        self.svc.look("frame")
        self.assertIn("a little better", self.svc.improve("ada"))
        self.assertEqual(self.book.count("Ada"), min(before + 1, 4))

    def test_it_needs_a_recent_single_face_and_a_known_name(self):
        self.remember("Ada", ADA)
        self.assertIn("haven't looked", self.svc.improve("Ada"))
        self.backend.faces = [ADA, BEN]
        self.svc.look("frame")
        self.assertIn("exactly one face", self.svc.improve("Ada"))
        self.backend.faces = [ADA]
        self.svc.look("frame")
        self.assertIn("don't know a Zed", self.svc.improve("Zed"))
        self.now[0] += 60
        self.assertIn("haven't looked", self.svc.improve("Ada"))

    def test_forgetting_also_drops_the_last_sighting(self):
        self.remember("Ada", ADA)
        self.backend.faces = [ADA]
        self.svc.look("frame")
        self.svc.forget("Ada")
        self.assertEqual(self.svc.status_line(), "")
        self.assertIn("don't know", self.svc.improve("Ada"))


class ThroughTheRobot(unittest.TestCase):
    def setUp(self):
        import bob
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        cfg = config.Config()
        cfg.stream.enabled = False
        cfg.faces.sample_gap_s = 0
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctrl = bob.Controller(cfg, sim=True, paused=True)
        self.addCleanup(self.ctrl.shutdown)
        self.backend = FakeBackend()
        self.ctrl.faces = FaceService(cfg.faces, FaceBook(Path(self.tmp.name) / "faces.json"), lambda: self.backend,
                                      sleep=lambda s: None)
        self.ctrl.brain.faces = self.ctrl.faces

    def test_off_by_default_and_says_how_to_turn_it_on(self):
        self.assertIn("off", self.ctrl.handle("/face"))
        self.assertIn("is off", self.ctrl.handle("/face remember Ada"))

    def test_only_owner_and_operators(self):
        self.assertIn("only the owner", self.ctrl.handle("/face on", role="viewer"))
        self.assertIn("only the owner", self.ctrl.handle("/face forget all", role="dashboard"))

    def test_the_whole_conversation_through_the_commands(self):
        self.assertIn("on", self.ctrl.handle("/face on"))
        self.backend.faces = [ADA]
        self.ctrl.camera.grab_bgr = lambda: "frame"
        self.assertIn("agrees", self.ctrl.handle("/face remember Ada", by="adam", role="operator"))
        self.assertIn("recognise Ada", self.ctrl.handle("/face remember confirm", by="adam", role="operator"))
        self.assertIn("Ada (", self.ctrl.handle("/face"))
        self.ctrl.faces.look("frame")
        self.assertIn("People I recognise in view", self.ctrl.brain._status([], False))
        self.assertIn("Ada", self.ctrl.brain._status([], False))
        self.assertIn("forgot Ada", self.ctrl.handle("/face forget Ada"))
        self.assertNotIn("People I recognise", self.ctrl.brain._status([], False))

    def test_claude_has_no_way_to_learn_or_forget_faces(self):
        names = [t["name"] for t in self.ctrl.brain.tools]
        self.assertFalse([n for n in names if "face" in n.lower() and n not in ("find_person", "follow_person")], names)
        self.assertIn("cannot learn or forget a face", self.ctrl.brain.system[0]["text"].replace("\\\n", " "))


if __name__ == "__main__":
    unittest.main()
