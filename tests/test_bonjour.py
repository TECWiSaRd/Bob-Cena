import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bonjour import Bonjour  # noqa: E402


class FakeProc:
    def __init__(self):
        self.alive, self.terminated = True, False

    def poll(self):
        return None if self.alive else 1

    def terminate(self):
        self.terminated, self.alive = True, False


class BonjourTests(unittest.TestCase):
    def make(self, tools, **kw):
        self.procs = []

        def popen(cmd, **k):
            self.cmd = cmd
            p = FakeProc()
            self.procs.append(p)
            return p

        return Bonjour("Bob (bobcena)", 8443, {"v": "1", "fp": "abcd"}, which=lambda n: n if n in tools else None,
                       popen=popen, retry_s=0.05, **kw)

    def test_the_pi_uses_avahi(self):
        b = self.make({"avahi-publish"})
        self.assertEqual(b.command(), ["avahi-publish", "-s", "Bob (bobcena)", "_bob._tcp", "8443", "v=1", "fp=abcd"])

    def test_a_mac_uses_dns_sd(self):
        self.assertEqual(self.make({"dns-sd"}).command()[:6], ["dns-sd", "-R", "Bob (bobcena)", "_bob._tcp", "local", "8443"])

    def test_no_tool_means_no_announcement_but_no_crash(self):
        b = self.make(set())
        self.assertFalse(b.start())

    def test_it_is_restarted_if_the_announcer_dies_and_stopped_with_bob(self):
        b = self.make({"avahi-publish"})
        self.assertTrue(b.start())
        deadline = time.monotonic() + 3
        while not self.procs and time.monotonic() < deadline:
            time.sleep(0.02)
        self.procs[0].alive = False                                   # avahi was restarted and took the announcer with it
        deadline = time.monotonic() + 5
        while len(self.procs) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertGreaterEqual(len(self.procs), 2)
        b.stop()
        self.assertTrue(self.procs[-1].terminated)


if __name__ == "__main__":
    unittest.main()
