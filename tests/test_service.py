import re
import unittest
from pathlib import Path

SERVICE = Path(__file__).resolve().parent.parent / "bob.service"


class ServiceFile(unittest.TestCase):
    def test_no_setting_has_a_comment_on_the_same_line(self):
        """systemd does not allow a trailing comment: it reads it as part of the value and ignores the setting
        (on the Pi that silently dropped Nice= and TimeoutStopSec=). Comments must be on their own lines."""
        for number, line in enumerate(SERVICE.read_text().splitlines(), 1):
            if re.match(r"^[A-Za-z]+=", line) and not line.startswith(("ExecStart", "ExecStop")):
                self.assertNotRegex(line, r"\s#", f"bob.service line {number} has a trailing comment: {line}")

    def test_the_settings_we_rely_on_are_there(self):
        text = SERVICE.read_text()
        for wanted in ("Nice=8\n", "TimeoutStopSec=20\n", "Restart=on-failure\n"):
            self.assertIn(wanted, text)


if __name__ == "__main__":
    unittest.main()
