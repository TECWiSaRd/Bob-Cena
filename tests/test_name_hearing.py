import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from listen import fix_name, strip_wake  # noqa: E402

ALIASES = config.MicConfig().name_aliases


class FixNameTests(unittest.TestCase):
    def test_mom_at_the_start_becomes_bob(self):
        self.assertEqual(fix_name("Mom, come here.", "Bob", ALIASES), "Bob, come here.")
        self.assertEqual(fix_name("mom what do you see", "Bob", ALIASES), "Bob what do you see")
        self.assertEqual(fix_name("Mom?", "Bob", ALIASES), "Bob?")

    def test_after_a_greeting(self):
        self.assertEqual(fix_name("Hey Mom, turn left", "Bob", ALIASES), "Hey Bob, turn left")
        self.assertEqual(fix_name("Okay hey mom stop", "Bob", ALIASES), "Okay hey Bob stop")

    def test_real_uses_of_the_word_are_left_alone(self):
        for text in ("Mom's coming over soon", "Tell my mom hello", "I called my mom", "Is that a mob?", "Come here, mom"):
            self.assertEqual(fix_name(text, "Bob", ALIASES), text, text)

    def test_only_one_fix_and_nothing_else_changes(self):
        self.assertEqual(fix_name("Mom, ask Mom if she is there", "Bob", ALIASES), "Bob, ask Mom if she is there")
        self.assertEqual(fix_name("", "Bob", ALIASES), "")
        self.assertEqual(fix_name("Hello there", "Bob", ALIASES), "Hello there")

    def test_the_list_can_be_changed(self):
        self.assertEqual(fix_name("Mom, hi", "Bob", ["bub"]), "Mom, hi")
        self.assertEqual(fix_name("Bub, hi", "Bob", ["bub"]), "Bob, hi")

    def test_the_text_wake_word_then_works_on_the_fixed_transcript(self):
        rest, found = strip_wake(fix_name("Hey Mom, what time is it", "Bob", ALIASES), ["bob"])
        self.assertTrue(found)
        self.assertEqual(rest, "what time is it")


if __name__ == "__main__":
    unittest.main()
