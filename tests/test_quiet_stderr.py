import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CHILD = textwrap.dedent("""
    import os, sys, warnings
    sys.path.insert(0, {root!r})
    from console import quiet_stderr
    with quiet_stderr({log!r}):
        sys.stderr.write("python warning\\n")
        warnings.warn("a library warning")
        os.write(2, b"native library output\\n")                # what libcamera and child programs do
        os.system("echo from a child program 1>&2")
    sys.stderr.write("after the screen closed\\n")
""")


class QuietStderrTests(unittest.TestCase):
    def test_noise_goes_to_the_file_and_the_terminal_stays_clean_until_the_end(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "logs" / "stderr.log"
            done = subprocess.run([sys.executable, "-c", CHILD.format(root=str(ROOT), log=str(log))],
                                  capture_output=True, text=True, timeout=20)
            for line in ("python warning", "a library warning", "native library output", "from a child program"):
                self.assertIn(line, log.read_text())
                self.assertNotIn(line, done.stderr)             # nothing reached the terminal while the screen was up
            self.assertIn("after the screen closed", done.stderr)   # and a crash message afterwards still would

    def test_an_unwritable_path_changes_nothing(self):
        code = ("import sys; sys.path.insert(0, %r)\nfrom console import quiet_stderr\n"
                "with quiet_stderr('/proc/nope/x.log'):\n    sys.stderr.write('still shown\\n')\n") % str(ROOT)
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20)
        self.assertIn("still shown", done.stderr)

    def test_a_big_log_is_rotated(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "stderr.log"
            log.write_text("x" * 2_100_000)
            subprocess.run([sys.executable, "-c", CHILD.format(root=str(ROOT), log=str(log))], capture_output=True, timeout=20)
            self.assertTrue((Path(d) / "stderr.log.1").exists())
            self.assertLess(log.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
