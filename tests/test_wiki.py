"""The wiki is generated from the manuals: every link must land on a real page, and nothing may keep a ".md" manual link."""
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import make_wiki  # noqa: E402


class Wiki(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name)
        make_wiki.build(out=cls.out)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def pages(self):
        return {p.stem: p for p in self.out.glob("*.md")}

    def test_every_manual_becomes_a_page_with_home_and_sidebar(self):
        n = len(list((ROOT / "manuals").glob("*.md")))
        pages = self.pages()
        self.assertEqual(len([k for k in pages if not k.startswith("_")]), n)
        for needed in ("Home", "_Sidebar", "_Footer", "09-Distance-sensor"):
            self.assertIn(needed, pages)
        sidebar = (self.out / "_Sidebar.md").read_text()
        self.assertEqual(sidebar.count("](") - 2, n - 1)       # all pages except Home, plus Home and the source link
        self.assertIn("(09-Distance-sensor)", sidebar)

    def test_every_link_lands_somewhere_real(self):
        pages = self.pages()
        for path in self.out.glob("*.md"):
            for target in re.findall(r"\]\(([^)\s]+)\)", path.read_text()):
                if target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                self.assertIn(target.split("#")[0], pages, f"{path.name} links to {target}")

    def test_no_markdown_file_links_are_left(self):
        for path in self.out.glob("*.md"):
            for target in re.findall(r"\]\(([^)\s]+)\)", path.read_text()):
                if not target.startswith("http"):
                    self.assertFalse(target.split("#")[0].endswith(".md"), f"{path.name}: {target}")

    def test_files_outside_the_manuals_link_to_the_repository(self):
        text = (self.out / "11-Microphone-and-wake-word.md").read_text()
        self.assertIn("https://github.com/TECWiSaRd/Bob-Cena/blob/main/TRAINING_HEY_BOB.md", text)

    def test_links_in_code_blocks_and_same_page_links_are_left_alone(self):
        names = {"01-x.md": "01-X"}
        text = "see [a](01-x.md#top) and [b](#here)\n```\n[c](01-x.md)\n```\n"
        out = make_wiki.rewrite_links(text, names)
        self.assertIn("[a](01-X#top)", out)
        self.assertIn("[b](#here)", out)
        self.assertIn("[c](01-x.md)", out)


if __name__ == "__main__":
    unittest.main()
