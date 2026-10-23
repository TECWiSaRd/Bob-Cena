import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import stream  # noqa: E402


class DashboardScriptTests(unittest.TestCase):
    def script(self) -> str:
        return re.search(r"<script>(.*)</script>", stream.DASH_PAGE, re.S).group(1)

    @unittest.skipUnless(shutil.which("node"), "node isn't installed")
    def test_the_page_script_is_valid_javascript(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "dash.js"
            path.write_text(self.script())
            done = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)

    def test_every_element_the_script_uses_exists_on_the_page(self):
        ids = set(re.findall(r"\bid=\"?([A-Za-z0-9_]+)", stream.DASH_PAGE))
        used = set(re.findall(r"\$\('([A-Za-z0-9_]+)'\)", self.script()))
        self.assertEqual(sorted(used - ids), [])

    def test_the_new_dashboard_pieces_are_there(self):
        for needle in ("roomcard", "eventscard", "sleep on", "goto", "usage", "vitals"):
            self.assertIn(needle, stream.DASH_PAGE)


if __name__ == "__main__":
    unittest.main()
