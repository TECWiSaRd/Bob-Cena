import json
import socket
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import radio  # noqa: E402
from radio import Radio, make_message  # noqa: E402

SECRET = "x" * 32


def wait_for(fn, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if fn():
            return True
        time.sleep(0.02)
    return False


class WifiRadioTests(unittest.TestCase):
    def pair(self, secret_b=SECRET):
        self.got_a, self.got_b = [], []
        self.a = Radio("Bob", "John", SECRET, "listen", "", 3, lambda s, t: self.got_a.append((s, t)),
                       transport="wifi", port=0, bind="127.0.0.1")
        self.a.start()
        self.assertTrue(wait_for(lambda: self.a.bound_port))
        self.b = Radio("John", "Bob", secret_b, "connect", "127.0.0.1", 3, lambda s, t: self.got_b.append((s, t)),
                       transport="wifi", port=self.a.bound_port)
        self.b.start()
        self.addCleanup(self.a.stop)
        self.addCleanup(self.b.stop)

    def test_two_robots_link_and_talk_over_tcp(self):
        self.pair()
        self.assertTrue(wait_for(lambda: self.a.connected and self.b.connected))
        self.assertEqual(self.a.send("hello John")[0], True)
        self.assertEqual(self.b.send("hi Bob")[0], True)
        self.assertTrue(wait_for(lambda: self.got_b == [("Bob", "hello John")] and self.got_a == [("John", "hi Bob")]))
        self.assertIn("Wi-Fi", self.a.status())

    def test_the_wrong_secret_never_links(self):
        self.pair(secret_b="y" * 32)
        time.sleep(1.0)
        self.assertFalse(self.a.connected or self.b.connected)
        self.assertEqual(self.got_a + self.got_b, [])
        self.assertGreaterEqual(self.a.rejected, 1)

    def test_a_stranger_who_connects_and_says_nothing_cannot_hold_the_slot(self):
        radio.HANDSHAKE_S = 0.8
        self.addCleanup(setattr, radio, "HANDSHAKE_S", 10.0)
        self.got_a = []
        a = Radio("Bob", "John", SECRET, "listen", "", 3, lambda s, t: self.got_a.append(t),
                  transport="wifi", port=0, bind="127.0.0.1")
        a.start()
        self.addCleanup(a.stop)
        self.assertTrue(wait_for(lambda: a.bound_port))
        stranger = socket.create_connection(("127.0.0.1", a.bound_port))
        self.addCleanup(stranger.close)
        time.sleep(0.3)
        b = Radio("John", "Bob", SECRET, "connect", "127.0.0.1", 3, lambda s, t: None, transport="wifi", port=a.bound_port)
        b.start()
        self.addCleanup(b.stop)
        self.assertTrue(wait_for(lambda: a.connected and b.connected, timeout=8))       # the real John got through

    def test_junk_from_a_stranger_is_rejected(self):
        a = Radio("Bob", "John", SECRET, "listen", "", 3, lambda s, t: self.fail("delivered junk"),
                  transport="wifi", port=0, bind="127.0.0.1")
        a.start()
        self.addCleanup(a.stop)
        self.assertTrue(wait_for(lambda: a.bound_port))
        s = socket.create_connection(("127.0.0.1", a.bound_port))
        self.addCleanup(s.close)
        s.sendall(b"not json\n" + json.dumps(make_message("wrong-secret-wrong-secret", "John", "msg", "do it")).encode() + b"\n")
        self.assertTrue(wait_for(lambda: a.rejected >= 2))
        self.assertFalse(a.connected)

    def test_it_reconnects_after_the_other_side_restarts(self):
        self.pair()
        self.assertTrue(wait_for(lambda: self.a.connected and self.b.connected))
        self.b._drop()                                         # the link breaks
        self.assertTrue(wait_for(lambda: not self.a.connected))
        self.assertTrue(wait_for(lambda: self.a.connected and self.b.connected, timeout=12))

    def test_settings_are_checked(self):
        with self.assertRaisesRegex(ValueError, "transport"):
            Radio("Bob", "John", SECRET, "listen", "", 3, lambda s, t: None, transport="carrier-pigeon")
        with self.assertRaisesRegex(ValueError, "host name or IP"):
            Radio("Bob", "John", SECRET, "connect", "", 3, lambda s, t: None, transport="wifi")
        with self.assertRaisesRegex(ValueError, "port"):
            Radio("Bob", "John", SECRET, "listen", "", 3, lambda s, t: None, transport="wifi", port=70000)

    def test_bluetooth_is_still_the_default(self):
        r = Radio("Bob", "John", SECRET, "listen", "", 3, lambda s, t: None)
        self.assertEqual(r.transport, "bluetooth")
        self.assertIn("Bluetooth", r.status())
        self.assertEqual(config.RadioConfig().transport, "bluetooth")

    def test_the_copy_in_john_prompt_matches_radio_py(self):
        import re
        root = Path(__file__).resolve().parent.parent
        embedded = re.search(r"```python\n(.*?)```", (root / "JOHN_PROMPT.md").read_text(), re.S).group(1)
        self.assertEqual(embedded, (root / "radio.py").read_text(), "re-paste radio.py into JOHN_PROMPT.md")


if __name__ == "__main__":
    unittest.main()
