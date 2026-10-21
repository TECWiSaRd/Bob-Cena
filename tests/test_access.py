"""Checks for per-person, per-Wi-Fi dashboard tokens. Run:  python3 -m unittest discover -s tests"""
import http.client
import json
import os
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from access import AccessPolicy, Lockout, current_wifi, parse_env  # noqa: E402

ENV = """\
# comment
ANTHROPIC_API_KEY=sk-ant-not-for-this-parser
BOB_STREAM_TOKEN=owner-secret-1234
TOKEN_KAI=kai-secret-12345
TOKEN_Sam = "sam-secret-12345"
TOKEN_SHORT=abc
WIFI[Kai's House]=KAI
WIFI["Sam Home"]=sam
WIFI[Shared]=KAI
WIFI[Shared]=SAM
WIFI[Nowhere]=GHOST
"""


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class ParseTests(unittest.TestCase):
    def test_reads_tokens_and_networks(self):
        tokens, wifi, problems = parse_env(ENV)
        self.assertEqual(tokens, {"kai": "kai-secret-12345", "sam": "sam-secret-12345"})       # names are lower-cased
        self.assertEqual(wifi["Kai's House"], ["kai"])
        self.assertEqual(wifi["Sam Home"], ["sam"])                                              # quotes inside brackets are fine
        self.assertEqual(wifi["Shared"], ["kai", "sam"])                                         # two people on one network
        self.assertEqual(wifi["Nowhere"], [])                                                    # a name with no token works for nobody
        self.assertTrue(any("TOKEN_SHORT" in p for p in problems))
        self.assertTrue(any("GHOST" in p for p in problems))

    def test_other_env_lines_are_ignored(self):
        tokens, _, _ = parse_env("ANTHROPIC_API_KEY=x\nTOKEN_=bad\nTOKENS_KAI=abcdefghij\n  # TOKEN_KAI=abcdefghij\n")
        self.assertEqual(tokens, {})

    def test_network_names_with_brackets_and_equals(self):
        _, wifi, _ = parse_env("TOKEN_A=abcdefghij\nWIFI[odd]name=1]=A\n")
        self.assertEqual(list(wifi), ["odd]name=1"])

    def test_wifi_name_from_nmcli_and_iwgetid(self):
        out = "no:Neighbour\nyes:Kai's House\\: 5G\n"
        self.assertEqual(current_wifi(lambda a, **k: out if a[0] == "nmcli" else None), "Kai's House: 5G")
        self.assertEqual(current_wifi(lambda a, **k: None if a[0] == "nmcli" else "Sam Home\n"), "Sam Home")
        self.assertIsNone(current_wifi(lambda a, **k: None))
        self.assertIsNone(current_wifi(lambda a, **k: "no:Other\n" if a[0] == "nmcli" else None))


    def test_nmcli_escapes_are_decoded_in_one_pass(self):
        out = "yes:a\\\\\\:b\n"                      # nmcli prints  a\\\:b   for the name  a\:b
        self.assertEqual(current_wifi(lambda a, **k: out if a[0] == "nmcli" else None), "a\\:b")


class PolicyTests(unittest.TestCase):
    def policy(self, ssid, clock=None):
        self.ssid = ssid
        tokens, wifi, problems = parse_env(ENV)
        return AccessPolicy("owner-secret-1234", tokens, wifi, wifi_reader=lambda: self.ssid, clock=clock or Clock(), background=False)

    def test_a_token_works_only_on_its_own_network(self):
        p = self.policy("Kai's House")
        self.assertEqual(p.check("kai-secret-12345"), "kai")
        self.assertIsNone(p.check("sam-secret-12345"))           # Sam's token is dead at Kai's house
        self.assertIsNone(p.check("nonsense"))

    def test_the_owner_works_everywhere(self):
        for ssid in ("Kai's House", "Sam Home", "Cafe", None):
            self.assertEqual(self.policy(ssid).check("owner-secret-1234"), "owner", ssid)

    def test_unknown_or_no_network_means_only_the_owner(self):
        for ssid in ("Cafe", None):
            p = self.policy(ssid)
            self.assertIsNone(p.check("kai-secret-12345"), ssid)
            self.assertEqual(sorted(p.valid()), ["owner"])

    def test_two_people_can_share_a_network(self):
        p = self.policy("Shared")
        self.assertEqual((p.check("kai-secret-12345"), p.check("sam-secret-12345")), ("kai", "sam"))

    def test_network_names_must_match_exactly(self):
        self.assertIsNone(self.policy("kai's house").check("kai-secret-12345"))

    def test_moving_to_another_network_changes_who_gets_in(self):
        clock = Clock()
        p = self.policy("Kai's House", clock)
        self.assertEqual(p.check("kai-secret-12345"), "kai")
        self.ssid = "Sam Home"
        self.assertEqual(p.check("kai-secret-12345"), "kai")      # the network name is cached for a few seconds...
        clock.t += 11
        self.assertIsNone(p.check("kai-secret-12345"))            # ...then re-read
        self.assertEqual(p.check("sam-secret-12345"), "sam")

    def test_a_slow_wifi_lookup_does_not_hold_up_other_requests(self):
        import threading
        gate, calls, clock = threading.Event(), [], Clock()
        def reader():
            calls.append(1)
            if len(calls) > 1:
                gate.wait(5)
            return "Kai's House"
        p = AccessPolicy("owner-secret-1234", {"kai": "kai-secret-12345"}, {"Kai's House": ["kai"]},
                         wifi_reader=reader, clock=clock)
        self.assertEqual(p.check("kai-secret-12345"), "kai")           # the first look is waited for
        clock.t += 11
        t0 = time.monotonic()
        self.assertEqual(p.check("kai-secret-12345"), "kai")           # stale answer, at once, while nmcli "hangs"
        self.assertEqual(p.check("owner-secret-1234"), "owner")
        self.assertLess(time.monotonic() - t0, 1.0)
        self.assertEqual(len(calls), 2)                                # and only one lookup is running
        gate.set()

    def test_a_failing_wifi_lookup_falls_back_to_owner_only(self):
        def boom():
            raise RuntimeError("nmcli exploded")
        p = AccessPolicy("owner-secret-1234", {"kai": "kai-secret-12345"}, {"Kai's House": ["kai"]}, wifi_reader=boom)
        self.assertIsNone(p.check("kai-secret-12345"))
        self.assertEqual(p.check("owner-secret-1234"), "owner")

    def test_strong_check_refuses_short_tokens(self):
        p = AccessPolicy("short")
        self.assertEqual(p.check("short"), "owner")               # fine for the video page, as before
        self.assertIsNone(p.check("short", strong=True))         # not for the dashboard, which can move the robot
        self.assertFalse(p.can_run_dashboard())
        self.assertTrue(AccessPolicy("", {"kai": "kai-secret-12345"}).can_run_dashboard())

    def test_nothing_configured(self):
        p = AccessPolicy("")
        self.assertFalse(p.configured)
        self.assertIsNone(p.check(""))
        self.assertIsNone(p.check("anything"))

    def test_describe_never_shows_a_secret(self):
        text = self.policy("Kai's House").describe()
        self.assertIn("Kai's House", text)
        self.assertIn("kai, owner", text)
        self.assertIn("sam", text)                                # tied to another network
        for secret in ("owner-secret-1234", "kai-secret-12345", "sam-secret-12345"):
            self.assertNotIn(secret, text)

    def test_load_reads_the_env_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / ".env"
            path.write_text(ENV)
            p = AccessPolicy.load(path, "owner-secret-1234", wifi_reader=lambda: "Sam Home")
            self.assertEqual(p.check("sam-secret-12345"), "sam")
            self.assertEqual(AccessPolicy.load(Path(d) / "missing", "").configured, False)


class LockoutTests(unittest.TestCase):
    def test_blocks_after_too_many_wrong_tries_then_forgives(self):
        clock = Clock()
        lock = Lockout(limit=3, window=60, clock=clock)
        for _ in range(2):
            lock.failed("1.2.3.4")
        self.assertFalse(lock.blocked("1.2.3.4"))
        lock.failed("1.2.3.4")
        self.assertTrue(lock.blocked("1.2.3.4"))
        self.assertFalse(lock.blocked("5.6.7.8"))                 # other addresses are unaffected
        clock.t += 61
        self.assertFalse(lock.blocked("1.2.3.4"))

    def test_memory_stays_bounded(self):
        lock = Lockout()
        for i in range(5000):
            lock.failed(f"10.0.{i // 256}.{i % 256}")
        self.assertLessEqual(len(lock._fails), 1001)


class FakeController:
    def __init__(self):
        self.handled, self.moves = [], []
        self.drive = SimpleNamespace(estop=SimpleNamespace(is_set=lambda: False), stop=lambda: None)

    def handle(self, text, by=None, role="owner"):
        self.handled.append((text, by))
        return "ok"

    def manual(self, l, r, s):
        self.moves.append((l, r))
        return "moving"


class WebTests(unittest.TestCase):
    def serve(self, policy):
        import stream
        cfg = config.StreamConfig()
        cfg.host, cfg.port = "0.0.0.0", 0
        srv = stream.StreamServer(cfg, camera=SimpleNamespace(capture_jpeg=lambda: None), policy=policy)
        srv.controller = FakeController()
        srv.status = lambda: {"mode": "AUTO"}
        srv.start()
        self.addCleanup(srv._httpd.server_close)
        self.addCleanup(srv._httpd.shutdown)
        return srv

    def get(self, srv, path):
        c = http.client.HTTPConnection("127.0.0.1", srv._httpd.server_address[1], timeout=5)
        c.request("GET", path)
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, body

    def post(self, srv, path, body):
        c = http.client.HTTPConnection("127.0.0.1", srv._httpd.server_address[1], timeout=5)
        data = json.dumps(body).encode()
        c.request("POST", path, data, {"Content-Type": "application/json", "Content-Length": str(len(data))})
        r = c.getresponse()
        r.read()
        c.close()
        return r.status

    def policy(self, ssid):
        tokens, wifi, _ = parse_env(ENV)
        self.ssid = ssid
        self.clock = Clock()
        return AccessPolicy("owner-secret-1234", tokens, wifi, wifi_reader=lambda: self.ssid, clock=self.clock, background=False)

    def test_only_the_token_for_this_network_opens_the_dashboard(self):
        srv = self.serve(self.policy("Kai's House"))
        self.assertEqual(self.get(srv, "/api/status?token=kai-secret-12345")[0], 200)
        self.assertEqual(self.get(srv, "/api/status?token=owner-secret-1234")[0], 200)
        self.assertEqual(self.get(srv, "/api/status?token=sam-secret-12345")[0], 401)
        self.assertEqual(self.get(srv, "/api/status")[0], 401)
        self.assertEqual(self.get(srv, "/dash?token=kai-secret-12345")[0], 200)

    def test_a_running_stream_stops_when_bob_leaves_the_network(self):
        import stream
        stream.RECHECK_S = 0.05
        self.addCleanup(setattr, stream, "RECHECK_S", 5.0)
        policy = self.policy("Kai's House")
        srv = self.serve(policy)
        srv.hub.get = lambda: b"\xff\xd8jpeg"
        srv.hub.interval = 0.02
        c = http.client.HTTPConnection("127.0.0.1", srv._httpd.server_address[1], timeout=5)
        c.request("GET", "/stream?token=kai-secret-12345")
        r = c.getresponse()
        self.assertEqual(r.status, 200)
        self.assertTrue(r.read1(100))
        self.ssid = "Sam Home"
        self.clock.t += 11
        deadline = time.monotonic() + 5
        data = b"x"
        while data and time.monotonic() < deadline:              # the server must hang up on its own
            data = r.read1(65536)
        self.assertEqual(data, b"")
        c.close()

    def test_the_video_page_follows_the_same_rule(self):
        srv = self.serve(self.policy("Sam Home"))
        self.assertEqual(self.get(srv, "/snapshot.jpg?token=kai-secret-12345")[0], 401)
        self.assertEqual(self.get(srv, "/snapshot.jpg?token=sam-secret-12345")[0], 503)         # allowed in; this fake has no camera

    def test_taking_bob_to_another_house_switches_the_tokens(self):
        srv = self.serve(self.policy("Kai's House"))
        self.assertEqual(self.get(srv, "/api/status?token=kai-secret-12345")[0], 200)
        self.ssid = "Sam Home"
        self.clock.t += 11
        self.assertEqual(self.get(srv, "/api/status?token=kai-secret-12345")[0], 401)
        self.assertEqual(self.get(srv, "/api/status?token=sam-secret-12345")[0], 200)

    def test_commands_are_recorded_under_the_persons_name(self):
        srv = self.serve(self.policy("Kai's House"))
        self.assertEqual(self.post(srv, "/api/cmd?token=kai-secret-12345", {"cmd": "/say hi"}), 200)
        self.assertEqual(self.post(srv, "/api/cmd?token=owner-secret-1234", {"cmd": "/say yo"}), 200)
        self.assertEqual(self.post(srv, "/api/cmd?token=sam-secret-12345", {"cmd": "/say no"}), 401)
        self.assertEqual(srv.controller.handled, [("/say hi", "kai"), ("/say yo", "owner")])

    def test_driving_works_with_a_personal_token(self):
        srv = self.serve(self.policy("Kai's House"))
        self.assertEqual(self.post(srv, "/api/drive?token=kai-secret-12345", {"left": 0.5, "right": 0.5}), 200)
        self.assertEqual(srv.controller.moves, [(0.5, 0.5)])

    def test_wrong_guesses_lock_that_address_out(self):
        srv = self.serve(self.policy("Kai's House"))
        codes = [self.get(srv, f"/api/status?token=guess{i}")[0] for i in range(12)]
        self.assertEqual(codes[:8], [401] * 8)
        self.assertEqual(codes[8:], [429] * 4)
        self.assertEqual(self.get(srv, "/api/status?token=kai-secret-12345")[0], 429)      # even the right one, for now
        srv.lockout._clock = lambda: 10_000_000.0                                            # a minute later...
        self.assertEqual(self.get(srv, "/api/status?token=kai-secret-12345")[0], 200)

    def test_short_tokens_never_open_the_dashboard(self):
        srv = self.serve(AccessPolicy("short", wifi_reader=lambda: None))
        self.assertEqual(self.get(srv, "/api/status?token=short")[0], 403)                   # the dashboard is off
        self.assertEqual(self.get(srv, "/snapshot.jpg?token=short")[0], 503)                  # the video page still accepts it

    def test_tokens_in_the_viewer_page_are_quoted(self):
        weird = AccessPolicy("owner&secret=1 2<script>")
        srv = self.serve(weird)
        status, body = self.get(srv, "/?token=owner%26secret%3D1%202%3Cscript%3E")
        self.assertEqual(status, 200)
        self.assertNotIn(b"<script>", body.split(b"?token=")[1][:60])
        self.assertIn(b"owner%26secret%3D1%202%3Cscript%3E", body)

    def test_no_tokens_at_all_keeps_the_stream_on_this_pi(self):
        srv = self.serve(AccessPolicy(""))
        self.assertEqual(srv._httpd.server_address[0], "127.0.0.1")

    def test_personal_tokens_alone_are_enough_to_open_the_network(self):
        tokens, wifi, _ = parse_env(ENV)
        srv = self.serve(AccessPolicy("", tokens, wifi, wifi_reader=lambda: "Kai's House"))
        self.assertEqual(srv._httpd.server_address[0], "0.0.0.0")
        self.assertEqual(self.get(srv, "/api/status?token=kai-secret-12345")[0], 200)


class EnvLoading(unittest.TestCase):
    def test_token_and_wifi_lines_stay_out_of_the_environment(self):
        import tempfile
        import bob
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / ".env"
            path.write_text("BOB_TEST_PLAIN=yes\nTOKEN_ZED=zed-secret-1234\nWIFI[Kai's House]=ZED\nBAD KEY=1\n")
            bob.load_env(path)
        self.addCleanup(os.environ.pop, "BOB_TEST_PLAIN", None)
        self.assertEqual(os.environ.get("BOB_TEST_PLAIN"), "yes")
        self.assertNotIn("TOKEN_ZED", os.environ)
        self.assertNotIn("WIFI[Kai's House]", os.environ)
        self.assertNotIn("BAD KEY", os.environ)


class ThroughTheRobot(unittest.TestCase):
    def setUp(self):
        import bob
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        cfg = config.Config()
        cfg.stream.enabled = False
        self.ctrl = bob.Controller(cfg, sim=True, paused=True)
        self.addCleanup(self.ctrl.shutdown)

    def test_access_command(self):
        self.ctrl.access = AccessPolicy("", wifi_reader=lambda: None)
        self.assertIn("no dashboard tokens", self.ctrl.handle("/access"))
        tokens, wifi, _ = parse_env(ENV)
        self.ctrl.access = AccessPolicy("owner-secret-1234", tokens, wifi, wifi_reader=lambda: "Sam Home")
        text = self.ctrl.handle("/access")
        self.assertIn("Sam Home", text)
        self.assertIn("owner, sam", text)
        self.assertNotIn("secret", text)


if __name__ == "__main__":
    unittest.main()
