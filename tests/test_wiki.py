"""The wiki is generated from the manuals: every link must land on a real page, file or heading, and odd markdown must survive."""
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import make_wiki  # noqa: E402

LINK = re.compile(r"\]\(([^)\s]+)")


def slug(heading: str) -> str:
    """GitHub's heading anchor: lowercase, punctuation dropped, spaces to hyphens."""
    s = re.sub(r"[`*_]", "", heading.strip().lower())
    s = re.sub(r"[^\w\- ]", "", s)
    return s.replace(" ", "-")


def anchors(text: str) -> set[str]:
    """Heading anchors as GitHub numbers them: a second heading with the same text becomes name-1, a third name-2."""
    out, seen, fenced = set(), {}, False
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        elif not fenced and re.match(r"#{1,6} ", line):
            base = slug(line.lstrip("# "))
            n = seen.get(base, 0)
            seen[base] = n + 1
            out.add(base if n == 0 else f"{base}-{n}")
    return out


class RealManuals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name)
        make_wiki.build(out=cls.out)
        cls.pages = {p.stem: p.read_text() for p in cls.out.glob("*.md")}

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_every_manual_becomes_a_page_with_home_and_sidebar(self):
        n = len(list((ROOT / "manuals").glob("*.md")))
        self.assertEqual(len([k for k in self.pages if not k.startswith("_")]), n)
        for needed in ("Home", "_Sidebar", "_Footer", "09-Distance-sensor"):
            self.assertIn(needed, self.pages)
        sidebar = self.pages["_Sidebar"]
        self.assertEqual(sidebar.count("](") - 2, n - 1)
        self.assertIn("(09-Distance-sensor)", sidebar)
        self.assertIn("This wiki has one page", self.pages["Home"])
        self.assertNotIn("This folder", self.pages["Home"])

    def test_page_links_land_on_a_real_page_and_a_real_heading(self):
        for name, text in self.pages.items():
            for target in LINK.findall(text):
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                page, _, frag = target.partition("#")
                dest = name if target.startswith("#") else page
                self.assertIn(dest, self.pages, f"{name} links to {target}")
                if frag:
                    self.assertIn(frag, anchors(self.pages[dest]), f"{name}: no heading #{frag} on {dest}")

    def test_no_markdown_file_links_are_left(self):
        for name, text in self.pages.items():
            for target in LINK.findall(text):
                if not target.startswith("http"):
                    self.assertFalse(target.split("#")[0].endswith(".md"), f"{name}: {target}")

    def test_links_to_repository_files_point_at_files_that_exist(self):
        base = make_wiki.REPO_URL + "/blob/main/"
        found = 0
        for name, text in self.pages.items():
            for target in LINK.findall(text):
                if target.startswith(base):
                    found += 1
                    rel = target[len(base):].split("#")[0].split("?")[0]
                    self.assertTrue((ROOT / rel).exists(), f"{name}: {target}")
        self.assertGreater(found, 0)
        self.assertIn(base + "TRAINING_HEY_BOB.md", self.pages["11-Microphone-and-wake-word"])


class Anchors(unittest.TestCase):
    def test_repeated_headings_are_numbered_like_github(self):
        text = "# T\n## Troubleshooting\n## Troubleshooting\n## Troubleshooting\n```\n## not a heading\n```\n"
        self.assertEqual(anchors(text), {"t", "troubleshooting", "troubleshooting-1", "troubleshooting-2"})


class OddMarkdown(unittest.TestCase):
    def site(self, files: dict[str, str], extra: dict[str, str] | None = None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "manuals").mkdir()
        for name, body in files.items():
            (root / "manuals" / name).write_text(body)
        for name, body in (extra or {}).items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
        return root

    def build(self, files, extra=None):
        root = self.site(files, extra)
        out = root / "out"
        make_wiki.build(root / "manuals", out)
        return {p.stem: p.read_text() for p in out.glob("*.md")}

    HOME = "# Bob: start here\n\nThis folder has one manual for each part.\n"

    def test_titles_reference_links_html_and_fences(self):
        pages = self.build({
            "00-START-HERE.md": self.HOME,
            "01-a-b.md": ('# Manual 1: A [b]\n\n'
                          'see [x](02-c.md "Title") and [y](<02-c.md#top>) and [r][ref]\n\n'
                          '[ref]: 02-c.md "Ref title"\n\n'
                          '<a href="02-c.md">h</a> <img src="pic.png">\n\n'
                          'shown as text: `[z](02-c.md)` and in a fence:\n'
                          '~~~\n[f](02-c.md)\n~~~\n\n'
                          '[after](02-c.md)\n'),
            "02-c.md": "# Manual 2: C\n\n## Top\n",
            "pic.png": "x",
        }, extra={"manuals/pic.png": "x"})
        a = pages["01-A-b"]
        self.assertIn('[x](02-C "Title")', a)
        self.assertIn("[y](02-C#top)", a)
        self.assertIn("[ref]: 02-C", a)
        self.assertIn('<a href="02-C">', a)
        self.assertIn("blob/main/manuals/pic.png?raw=true", a)
        self.assertIn("`[z](02-c.md)`", a)             # inline code untouched
        self.assertIn("~~~\n[f](02-c.md)\n~~~", a)      # tilde fence untouched
        self.assertIn("[after](02-C)", a)              # and the fence really closed
        self.assertIn("A \\[b\\]", pages["_Sidebar"])  # brackets in a title cannot break the sidebar link

    def test_a_file_next_to_the_manuals_resolves_from_manuals(self):
        pages = self.build({"00-START-HERE.md": self.HOME + "[n](notes.txt) [r](../README.md) [i](images/w.png)\n"},
                           extra={"manuals/notes.txt": "n", "README.md": "r", "manuals/images/w.png": "i"})
        home = pages["Home"]
        self.assertIn("blob/main/manuals/notes.txt)", home)
        self.assertIn("blob/main/README.md)", home)
        self.assertIn("blob/main/manuals/images/w.png?raw=true)", home)

    def test_a_dead_link_stops_the_build(self):
        with self.assertRaises(make_wiki.LinkError):
            self.build({"00-START-HERE.md": self.HOME + "[n](nope.txt)\n"})
        with self.assertRaises(make_wiki.LinkError):
            self.build({"00-START-HERE.md": self.HOME + "[n](../../outside.txt)\n"})

    def test_two_manuals_with_the_same_page_name_are_refused(self):
        with self.assertRaises(make_wiki.LinkError):
            self.build({"00-START-HERE.md": self.HOME, "05-a-b.md": "# x\n", "05-a b.md": "# y\n"})

    def test_code_is_left_alone_but_list_text_is_not(self):
        body = (self.HOME +
                "\n    indented code with [x](02-c.md) and foo](bar.txt)\n\n"
                "- a list item\n\n    continues here with [y](02-c.md)\n\n"
                "a `span that\nruns over [z](02-c.md)` lines and [w](02-c.md)\n\n"
                "`x` [a]: notes.txt\n\n"
                "````\n```\n[f](02-c.md)\n```\n[g](02-c.md)\n````\n\n[after](02-c.md)\n")
        pages = self.build({"00-START-HERE.md": body, "02-c.md": "# C\n"})
        home = pages["Home"]
        self.assertIn("    indented code with [x](02-c.md) and foo](bar.txt)", home)
        self.assertIn("    continues here with [y](02-C)", home)          # a list's continuation is prose
        self.assertIn("runs over [z](02-c.md)` lines and [w](02-C)", home)
        self.assertIn("`x` [a]: notes.txt", home)                         # not a definition: it isn't at the line start
        self.assertIn("```\n[f](02-c.md)\n```\n[g](02-c.md)\n````", home)  # the shorter ``` did not close the block
        self.assertIn("[after](02-C)", home)

    def test_directories_and_encoded_names(self):
        pages = self.build({"00-START-HERE.md": self.HOME + "[d](../tests/) [f](my%20file.txt)\n"},
                           extra={"tests/t.py": "x", "manuals/my file.txt": "x"})
        home = pages["Home"]
        self.assertIn("/tree/main/tests)", home)
        self.assertIn("/blob/main/manuals/my%20file.txt)", home)

    def test_a_reworded_home_page_is_noticed(self):
        with self.assertRaises(make_wiki.LinkError):
            self.build({"00-START-HERE.md": "# Bob: start here\n\nThis directory holds the manuals.\n"})

    def test_a_manual_without_a_heading_gets_a_readable_sidebar_label(self):
        pages = self.build({"00-START-HERE.md": self.HOME, "09-distance-sensor.md": "no heading here\n"})
        self.assertIn("[09 Distance sensor](09-Distance-sensor)", pages["_Sidebar"])


if __name__ == "__main__":
    unittest.main()
