import http.client
import json
import os
import secrets
import ssl
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import appapi  # noqa: E402
import certs  # noqa: E402
import config  # noqa: E402
from appapi import DeviceStore, Pairing, client_proof, normalize_code, server_proof, show_code  # noqa: E402

HAVE_OPENSSL = certs.ensure_cert(Path(tempfile.mkdtemp()), "testhost") is not None


class Clock:
    t = 100.0

    def __call__(self):
        return self.t


class DeviceStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "devices.json"

    def test_a_token_works_once_issued_and_only_its_hash_is_stored(self):
        store = DeviceStore(self.path)
        ident, token = store.add("Adam's Mac", "adam")
        self.assertEqual(store.check(token), ident)
        self.assertIsNone(store.check(token + "x"))
        self.assertIsNone(store.check(""))
        self.assertNotIn(token, self.path.read_text())
        self.assertEqual(oct(self.path.stat().st_mode)[-3:], "600")

    def test_it_survives_a_restart_and_names_stay_unique(self):
        store = DeviceStore(self.path)
        a = store.add("Phone", "adam")
        b = store.add("Phone", "adam")
        self.assertNotEqual(a[0], b[0])
        again = DeviceStore(self.path)
        self.assertEqual(again.check(a[1]), a[0])
        self.assertEqual(again.check(b[1]), b[0])

    def test_removing_a_device_cuts_it_off(self):
        store = DeviceStore(self.path)
        ident, token = store.add("Phone", "adam")
        self.assertTrue(store.remove(ident.upper()))
        self.assertIsNone(store.check(token))
        self.assertFalse(store.remove("Phone"))

    def test_a_corrupt_file_is_kept_aside(self):
        self.path.write_text("{nope")
        store = DeviceStore(self.path)
        self.assertEqual(store.devices, {})
        self.assertTrue(self.path.with_name("devices.json.bad").exists())

    def test_there_is_a_limit(self):
        store = DeviceStore(self.path)
        for i in range(appapi.MAX_DEVICES):
            store.add(f"d{i}")
        with self.assertRaisesRegex(ValueError, "paired already"):
            store.add("one too many")


class PairingTests(unittest.TestCase):
    FP = "ab" * 32

    def setUp(self):
        self.clock = Clock()
        self.store = DeviceStore(None)
        self.pairing = Pairing(self.store, self.FP, "Bob", clock=self.clock)

    def attempt(self, code, fp=None, nonce=None):
        nonce = nonce or secrets.token_urlsafe(12)
        return nonce, self.pairing.redeem("My Mac", nonce, client_proof(code, nonce, fp or self.FP))

    def test_the_right_code_pairs_and_the_reply_proves_bob_knew_it(self):
        code = self.pairing.new_code("adam")
        nonce, reply = self.attempt(show_code(code).lower())              # typed with dashes and in lower case
        self.assertIsNotNone(reply)
        self.assertEqual(reply["fingerprint"], self.FP)
        self.assertEqual(reply["server_proof"], server_proof(code, nonce, self.FP, reply["token"]))
        self.assertEqual(self.store.check(reply["token"]), reply["device"])

    def test_a_code_works_once(self):
        code = self.pairing.new_code("adam")
        self.assertIsNotNone(self.attempt(code)[1])
        self.assertIsNone(self.attempt(code)[1])

    def test_codes_expire(self):
        code = self.pairing.new_code("adam")
        self.clock.t += appapi.CODE_LIFETIME + 1
        self.assertIsNone(self.attempt(code)[1])

    def test_someone_in_the_middle_with_another_certificate_fails_the_proof(self):
        code = self.pairing.new_code("adam")
        _, reply = self.attempt(code, fp="cd" * 32)                       # the app saw a different certificate than Bob's
        self.assertIsNone(reply)
        self.assertIsNotNone(self.attempt(code)[1])                       # and the real attempt still works afterwards

    def test_the_code_is_burned_after_too_many_wrong_proofs(self):
        code = self.pairing.new_code("adam")
        for _ in range(appapi.MAX_WRONG_PER_CODE):
            self.assertIsNone(self.attempt("WRONGWRONG12")[1])
        self.assertIsNone(self.attempt(code)[1])                          # too late: it was destroyed
        self.assertEqual(self.pairing.open_codes(), 0)

    def test_garbage_input_is_refused(self):
        self.pairing.new_code("adam")
        self.assertIsNone(self.pairing.redeem("x", None, "abc"))
        self.assertIsNone(self.pairing.redeem("x", "short", "abc"))
        self.assertIsNone(self.pairing.redeem("x", "a" * 100, 123))

    def test_codes_are_long_and_easy_to_type(self):
        code = self.pairing.new_code("adam")
        self.assertEqual(len(code), 12)
        self.assertTrue(set(code) <= set(appapi.ALPHABET))
        self.assertEqual(normalize_code("k7pq-2m9x-4twd"), "K7PQ2M9X4TWD")
        self.assertEqual(show_code("ABCDEFGHJKMN"), "ABCD-EFGH-JKMN")

    def test_only_a_few_codes_are_open_at_once(self):
        first = self.pairing.new_code("a")
        for _ in range(3):
            self.pairing.new_code("a")
        self.assertEqual(self.pairing.open_codes(), 3)
        self.assertIsNone(self.attempt(first)[1])                         # the oldest was dropped


@unittest.skipUnless(HAVE_OPENSSL, "openssl isn't installed")
class CertTests(unittest.TestCase):
    def test_a_certificate_is_made_once_and_kept(self):
        with tempfile.TemporaryDirectory() as d:
            cert, key, fp = certs.ensure_cert(Path(d) / "certs", "bobcena.local")
            self.assertEqual(oct(key.stat().st_mode)[-3:], "600")
            self.assertEqual(len(fp), 64)
            again = certs.ensure_cert(Path(d) / "certs", "other")
            self.assertEqual(again[2], fp)                                # not regenerated
            self.assertEqual(certs.fingerprint(cert), fp)

    def test_no_openssl_is_not_fatal(self):
        def boom(*a, **k):
            raise FileNotFoundError("openssl")
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(certs.ensure_cert(Path(d) / "certs", run=boom))


class FakeController:
    def __init__(self):
        self.cfg = SimpleNamespace(radio=SimpleNamespace(name="Bob"))
        self.handled, self.moves, self.stops = [], [], 0
        self.drive = SimpleNamespace(stop=self._stop)

    def _stop(self):
        self.stops += 1

    def handle(self, line, by=None, role="owner"):
        self.handled.append((line, by, role))
        return "ok"

    def manual(self, l, r, s):
        self.moves.append((l, r))
        return "moved"


@unittest.skipUnless(HAVE_OPENSSL, "openssl isn't installed")
class HttpsApiTests(unittest.TestCase):
    def setUp(self):
        import stream
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        cfg = config.StreamConfig()
        cfg.host, cfg.port, cfg.https_port, cfg.bonjour = "127.0.0.1", 0, 0, False
        self.srv = stream.StreamServer(cfg, SimpleNamespace(capture_jpeg=lambda: b"\xff\xd8jpeg"), base=Path(self.tmp.name))
        self.ctrl = FakeController()
        self.srv.controller = self.ctrl
        self.srv.status = lambda: {"mode": "AUTO"}
        self.srv.start()
        self.addCleanup(self.srv.stop)
        self.port = self.srv._httpsd.server_address[1]
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE                              # the app pins the fingerprint instead (tested below)

    def call(self, method, path, body=None, token=None, headers=None):
        c = http.client.HTTPSConnection("127.0.0.1", self.port, timeout=5, context=self.ctx)
        h = dict(headers or {})
        if token:
            h["Authorization"] = f"Bearer {token}"
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        c.request(method, path, data, h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        try:
            return r.status, json.loads(raw)
        except ValueError:
            return r.status, raw

    def pair(self, code=None, device="Test Mac"):
        code = code or self.srv.pairing.new_code("adam")
        nonce = secrets.token_urlsafe(12)
        seen = self.seen_fingerprint()
        status, reply = self.call("POST", "/api/v1/pair", {"device": device, "nonce": nonce, "proof": client_proof(code, nonce, seen)})
        return code, nonce, status, reply

    def seen_fingerprint(self):
        import hashlib
        import socket
        with socket.create_connection(("127.0.0.1", self.port)) as raw, self.ctx.wrap_socket(raw) as tls:
            return hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest()

    def test_the_whole_pairing_flow(self):
        self.assertEqual(self.call("GET", "/api/v1/info")[1]["fingerprint"], self.seen_fingerprint())
        code, nonce, status, reply = self.pair()
        self.assertEqual(status, 200)
        self.assertEqual(reply["server_proof"], server_proof(code, nonce, self.seen_fingerprint(), reply["token"]))
        token = reply["token"]
        self.assertEqual(self.call("GET", "/api/v1/status", token=token), (200, {"mode": "AUTO"}))
        self.assertEqual(self.call("POST", "/api/v1/cmd", {"cmd": "/say hi"}, token=token)[1], {"output": "ok"})
        self.assertEqual(self.ctrl.handled[-1][:2], ("/say hi", "app:Test Mac"))

    def test_nothing_works_without_pairing(self):
        for method, path in (("GET", "/api/v1/status"), ("POST", "/api/v1/cmd"), ("GET", "/api/v1/stream"), ("GET", "/api/v1/snapshot")):
            self.assertEqual(self.call(method, path, {} if method == "POST" else None)[0], 401, path)
        self.assertEqual(self.call("GET", "/api/v1/status", token="made-up-token")[0], 401)

    def test_a_wrong_code_does_not_pair_and_repeated_guessing_is_locked_out(self):
        self.srv.pairing.new_code("adam")
        statuses = [self.pair(code="WRONGWRONG12")[2] for _ in range(10)]
        self.assertEqual(statuses[0], 401)
        self.assertEqual(statuses[-1], 429)

    def test_the_app_api_refuses_plain_http(self):
        c = http.client.HTTPConnection("127.0.0.1", self.srv._httpd.server_address[1], timeout=5)
        c.request("GET", "/api/v1/info")
        r = c.getresponse()
        self.assertEqual(r.status, 403)
        self.assertIn("https", r.read().decode())

    def test_the_browser_pages_are_not_served_on_the_secure_port_without_a_token(self):
        for path in ("/", "/dash", "/stream", "/snapshot.jpg", "/api/status"):
            self.assertEqual(self.call("GET", path)[0], 403, path)
        self.assertEqual(self.call("POST", "/api/cmd", {"cmd": "/say hi"})[0], 403)

    def test_drive_is_clamped_and_zero_stops(self):
        token = self.pair()[3]["token"]
        self.call("POST", "/api/v1/drive", {"left": 9, "right": -9}, token=token)
        self.call("POST", "/api/v1/drive", {"left": 0, "right": 0}, token=token)
        self.assertEqual(self.ctrl.moves, [(1.0, -1.0)])
        self.assertEqual(self.ctrl.stops, 1)
        self.assertEqual(self.call("POST", "/api/v1/drive", {"left": "x"}, token=token)[0], 400)

    def test_snapshot_and_stream_need_the_token_and_stop_when_unpaired(self):
        token = self.pair()[3]["token"]
        self.assertEqual(self.call("GET", "/api/v1/snapshot", token=token)[0], 200)
        self.srv.hub.interval = 0.02
        import stream
        stream.RECHECK_S = 0.1
        self.addCleanup(setattr, stream, "RECHECK_S", 5.0)
        c = http.client.HTTPSConnection("127.0.0.1", self.port, timeout=5, context=self.ctx)
        c.request("GET", "/api/v1/stream", headers={"Authorization": f"Bearer {token}"})
        r = c.getresponse()
        self.assertEqual(r.status, 200)
        self.assertTrue(r.read1(100))
        self.assertEqual(self.call("POST", "/api/v1/unpair", {}, token=token)[1], {"removed": True})
        deadline = time.monotonic() + 5
        data = b"x"
        while data and time.monotonic() < deadline:                       # the stream must end by itself once unpaired
            data = r.read1(65536)
        self.assertEqual(data, b"")
        self.assertEqual(self.call("GET", "/api/v1/status", token=token)[0], 401)

    def test_a_client_that_never_finishes_the_handshake_does_not_block_others(self):
        import socket
        stalled = socket.create_connection(("127.0.0.1", self.port))
        self.addCleanup(stalled.close)
        t0 = time.monotonic()
        self.assertEqual(self.call("GET", "/api/v1/info")[0], 200)
        self.assertLess(time.monotonic() - t0, 3)

    def test_pinning_a_wrong_fingerprint_would_be_noticed(self):
        self.assertNotEqual(self.seen_fingerprint(), "00" * 32)
        self.assertEqual(self.seen_fingerprint(), self.srv.fingerprint)


class RobotCommandTests(unittest.TestCase):
    def setUp(self):
        import bob
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        cfg = config.Config()
        cfg.stream.enabled = False
        self.ctrl = bob.Controller(cfg, sim=True, paused=True)
        self.addCleanup(self.ctrl.shutdown)

    def test_without_the_secure_port_the_commands_explain(self):
        self.assertIn("isn't running", self.ctrl.handle("/pair"))
        self.assertIn("isn't running", self.ctrl.handle("/devices"))

    def test_only_owner_and_operators_pair_and_manage_devices(self):
        for cmd in ("/pair", "/devices", "/devices remove x"):
            for role in ("viewer", "dashboard"):
                self.assertIn("only the owner or an operator", self.ctrl.handle(cmd, by="x", role=role), (cmd, role))

    def test_claude_has_no_way_to_pair_a_device(self):
        self.assertFalse({t["name"] for t in self.ctrl.brain.tools if "pair" in t["name"] or "device" in t["name"]})


if __name__ == "__main__":
    unittest.main()
