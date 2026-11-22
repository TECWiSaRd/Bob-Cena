import asyncio
import http.client
import json
import os
import secrets
import ssl
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import appapi  # noqa: E402
import blecodec  # noqa: E402
import blelink  # noqa: E402
import config  # noqa: E402

KEY = bytes(range(32)).hex()
NONCE = "0011223344556677"


class TheMessageFormat(unittest.TestCase):
    def test_shared_vectors_the_app_must_match(self):
        """The same numbers are checked in app/test/ble_codec_test.dart: if one side changes, the other test fails."""
        dev = blecodec.short_id("Adam's MacBook")
        self.assertEqual(dev, "a1a0a419")
        self.assertEqual(blecodec.mac(KEY, dev, NONCE, 1, "D 0.50 -0.50"), "c28b205c56df1c00")
        self.assertEqual(blecodec.mac(KEY, dev, NONCE, 2, "S"), "619b9d570f114191")
        self.assertEqual(blecodec.mac(KEY, dev, NONCE, 3, "C /speed 0.3"), "5398eb141d2dff12")

    def test_the_signature_depends_on_everything(self):
        base = blecodec.mac(KEY, "a1a0a419", NONCE, 1, "D 0.50 -0.50")
        for other in (blecodec.mac(KEY, "a1a0a41a", NONCE, 1, "D 0.50 -0.50"), blecodec.mac(KEY, "a1a0a419", "00" * 8, 1, "D 0.50 -0.50"),
                      blecodec.mac(KEY, "a1a0a419", NONCE, 2, "D 0.50 -0.50"), blecodec.mac(KEY, "a1a0a419", NONCE, 1, "D 0.50 0.50"),
                      blecodec.mac("ff" * 32, "a1a0a419", NONCE, 1, "D 0.50 -0.50")):
            self.assertNotEqual(base, other)

    def test_lines_are_cut_into_small_packets_and_put_back(self):
        text = "C a1a0a419 7 5398eb141d2dff12 /say hello there, everybody"
        pieces = blecodec.chunks(text)
        self.assertTrue(all(len(p) <= blecodec.CHUNK for p in pieces))
        assembler = blecodec.LineAssembler()
        got = []
        for p in pieces:
            got += assembler.feed(p)
        self.assertEqual(got, [text])

    def test_several_lines_in_one_write_and_a_line_split_anywhere(self):
        a = blecodec.LineAssembler()
        self.assertEqual(a.feed(b"E\nS x\n"), ["E", "S x"])
        self.assertEqual(a.feed(b"D a"), [])
        self.assertEqual(a.feed(b"bc 1\r\n"), ["D abc 1"])           # a carriage return is trimmed

    def test_garbage_cannot_pile_up(self):
        a = blecodec.LineAssembler(limit=50)
        self.assertEqual(a.feed(b"x" * 400), [])                      # far too long: thrown away...
        self.assertEqual(a.feed(b"x" * 100 + b"\nE\n"), ["E"])        # ...up to its newline, and the next line is fine
        t = [0.0]
        b = blecodec.LineAssembler(stale_s=3.0, clock=lambda: t[0])
        b.feed(b"half a li")
        t[0] = 10.0                                                   # never finished: forgotten
        self.assertEqual(b.feed(b"E\n"), ["E"])


class FakeController:
    def __init__(self):
        self.moves, self.stops, self.estops, self.handled = [], 0, [], []
        self.drive = SimpleNamespace(stop=self._stop, estop=threading.Event(), speed_cap=0.8)
        self.controls = SimpleNamespace(auto=False)
        self.drive_mode = False
        self.refuse = ""

    def _stop(self):
        self.stops += 1

    def manual(self, left, right, seconds, *a, **k):
        if self.refuse:
            return self.refuse
        self.moves.append((left, right, seconds))
        return f"manual move L={left:+.2f} R={right:+.2f} {seconds:.1f}s"

    def estop(self, source="console"):
        self.estops.append(source)
        self.drive.estop.set()

    def handle(self, line, by=None, role="owner"):
        self.handled.append((line, by, role))
        return "ok"


class CoreCase(unittest.TestCase):
    def setUp(self):
        self.t = [1000.0]
        self.devices = appapi.DeviceStore(None)
        self.ident, _ = self.devices.add("Adam's MacBook")
        self.key = self.devices.ble_key(self.ident)
        self.dev = blecodec.short_id(self.ident)
        self.ctrl = FakeController()
        self.cfg = config.BleConfig(enabled=True)
        self.core = blelink.BleCore(self.cfg, self.ctrl, self.devices, clock=lambda: self.t[0], nonce=lambda: NONCE,
                                    label_of=lambda ident: "Adam")
        self.ctr = 0

    def hello(self, dev=None):
        return self.core.handle(f"H {dev or self.dev}")

    def signed(self, cmd, body=None, extra="", ctr=None, key=None, dev=None):
        self.ctr = (self.ctr + 1) if ctr is None else ctr
        dev = dev or self.dev
        body = body if body is not None else cmd
        sig = blecodec.mac(key or self.key, dev, NONCE, self.ctr, body)
        if cmd == "D":
            return f"D {dev} {self.ctr} {body[2:]} {sig}"
        if cmd == "C":
            return f"C {dev} {self.ctr} {sig} {body[2:]}"
        return f"{cmd} {dev} {self.ctr} {sig}"

    def go(self, *args, **kw):
        return self.core.handle(self.signed(*args, **kw))


class Greeting(CoreCase):
    def test_a_known_device_gets_a_nonce(self):
        self.assertEqual(self.hello(), [f"N {NONCE}"])

    def test_unknown_devices_and_devices_without_a_key_do_not(self):
        self.assertEqual(self.hello("deadbeef"), ["ERR unknown device"])
        other, _ = self.devices.add("Another phone")                  # paired, but never asked for a Bluetooth key
        self.assertEqual(self.hello(blecodec.short_id(other)), ["ERR unknown device"])
        self.assertEqual(self.core.handle("H"), ["ERR unknown device"])

    def test_nothing_works_without_a_hello(self):
        self.assertEqual(self.go("S"), ["ERR session"])
        self.assertEqual(self.ctrl.stops, 0)

    def test_a_session_expires(self):
        self.hello()
        self.t[0] += blelink.SESSION_S + 1
        self.assertEqual(self.go("S"), ["ERR session"])

    def test_an_unpaired_device_loses_its_session_at_once(self):
        self.hello()
        self.assertEqual(self.go("S"), ["OK"])
        self.devices.remove(self.ident)
        self.assertEqual(self.go("S"), ["ERR session"])
        self.assertEqual(self.ctrl.stops, 1)


class Driving(CoreCase):
    def setUp(self):
        super().setUp()
        self.hello()

    def test_a_drive_pulse_moves_him_for_a_short_pulse(self):
        self.assertEqual(self.go("D", "D 0.50 -0.50"), [])
        self.assertEqual(self.ctrl.moves, [(0.5, -0.5, 0.4)])

    def test_zero_stops_and_values_are_clamped(self):
        self.go("D", "D 0.00 0.00")
        self.assertEqual((self.ctrl.stops, self.ctrl.moves), (1, []))
        self.go("D", "D 5 -9")
        self.assertEqual(self.ctrl.moves, [(1.0, -1.0, 0.4)])

    def test_nonsense_numbers_do_nothing(self):
        for body in ("D nan 0.5", "D inf 0", "D abc 1"):
            self.assertEqual(self.go("D", body), ["ERR what"], body)
        self.assertEqual(self.ctrl.moves, [])

    def test_a_refusal_is_reported(self):
        self.ctrl.refuse = "E-stop active - /clear first"
        self.assertEqual(self.go("D", "D 0.50 0.50"), ["ERR E-stop active - /clear first"])

    def test_stop_and_status(self):
        self.assertEqual(self.go("S"), ["OK"])
        self.ctrl.controls.auto = True
        self.assertEqual(self.go("T"), ["T e=0 a=1 d=0 s=0.80"])


class Signatures(CoreCase):
    def setUp(self):
        super().setUp()
        self.hello()

    def test_a_wrong_signature_is_refused_and_changes_nothing(self):
        self.assertEqual(self.go("D", "D 1 1", key="ff" * 32), ["ERR auth"])
        self.assertEqual(self.ctrl.moves, [])

    def test_changing_the_numbers_after_signing_is_caught(self):
        line = self.signed("D", "D 0.10 0.10")
        tampered = line.replace("0.10 0.10", "1.00 1.00")
        self.assertEqual(self.core.handle(tampered), ["ERR auth"])
        self.assertEqual(self.ctrl.moves, [])

    def test_the_same_message_twice_and_older_ones_are_ignored(self):
        line = self.signed("D", "D 0.50 0.50", ctr=5)
        self.core.handle(line)
        self.core.handle(line)                                         # a repeat
        self.core.handle(self.signed("D", "D 0.20 0.20", ctr=3))       # an older one, even though correctly signed
        self.assertEqual(self.ctrl.moves, [(0.5, 0.5, 0.4)])

    def test_a_recorded_message_does_not_work_in_a_new_session(self):
        recorded = self.signed("D", "D 0.50 0.50", ctr=1)
        self.core.nonce = None
        self.core._nonce = lambda: "ff" * 8                            # the next hello makes another nonce
        self.hello()
        self.assertEqual(self.core.handle(recorded), ["ERR auth"])
        self.assertEqual(self.ctrl.moves, [])

    def test_a_signature_for_another_device_does_not_work(self):
        other, _ = self.devices.add("Another phone")
        self.devices.ble_key(other)
        self.assertEqual(self.go("S", dev=blecodec.short_id(other)), ["ERR session"])      # it never said hello
        self.assertEqual(self.ctrl.stops, 0)

    def test_malformed_messages_are_refused_politely(self):
        for line in ("D", "D x", f"D {self.dev} one 0.5 0.5 abc", f"D {self.dev} 1 0.5 abc", f"S {self.dev}", "X 1 2 3", "hello there"):
            self.assertIn(self.core.handle(line)[0], ("ERR what", "ERR auth", "ERR session"), line)
        self.assertEqual((self.ctrl.moves, self.ctrl.stops), ([], 0))

    def test_too_many_wrong_signatures_lock_him_out_but_never_the_emergency_stop(self):
        for _ in range(blelink.MAX_FAILS):
            self.t[0] += 0.2
            self.go("S", key="ff" * 32)
        self.t[0] += 0.2
        self.assertEqual(self.go("S"), ["ERR locked"])                 # even a right signature
        self.assertEqual(self.core.handle("E"), ["OK stopped"])
        self.assertEqual(self.ctrl.estops, ["bluetooth"])
        self.t[0] += blelink.LOCK_S + 1
        self.hello()
        self.assertEqual(self.go("S"), ["OK"])

    def test_he_acts_on_only_so_many_messages_a_second(self):
        self.cfg.max_per_second = 5
        self.t[0] += 1.1                                               # (the hello in setUp used up one slot of the first second)
        for _ in range(12):
            self.go("S")
        self.assertEqual(self.ctrl.stops, 5)
        self.t[0] += 1.1
        self.go("S")
        self.assertEqual(self.ctrl.stops, 6)


class TheEmergencyStop(CoreCase):
    def test_anyone_nearby_can_stop_him_without_a_hello(self):
        self.assertEqual(self.core.handle("E"), ["OK stopped"])
        self.assertTrue(self.ctrl.drive.estop.is_set())

    def test_that_can_be_switched_off_leaving_only_a_signed_stop(self):
        self.cfg.open_estop = False
        self.assertEqual(self.core.handle("E"), ["ERR what"])
        self.assertEqual(self.ctrl.estops, [])
        self.hello()
        self.assertEqual(self.go("E"), ["OK stopped"])
        self.assertEqual(self.ctrl.estops, ["bluetooth"])


class Commands(CoreCase):
    def setUp(self):
        super().setUp()
        self.hello()

    def test_a_signed_command_runs_as_that_person_and_the_answer_comes_back(self):
        self.core.run_command = lambda text, by=None: f"did {text} for {by}\nsecond line\n\n" + "x" * 300
        out = self.go("C", "C /speed 0.3")
        self.assertEqual(out[0], "R did /speed 0.3 for app:Adam")
        self.assertEqual(out[1], "R second line")
        self.assertTrue(all(len(line) <= 102 for line in out))
        self.assertLessEqual(len(out), 6)

    def test_an_empty_answer_is_just_ok(self):
        self.core.run_command = lambda text, by=None: ""
        self.assertEqual(self.go("C", "C /nothing"), ["OK"])

    def test_the_command_cannot_be_changed_after_signing(self):
        line = self.signed("C", "C /say hi")
        self.assertEqual(self.core.handle(line.replace("/say hi", "/shutdown confirm")), ["ERR auth"])
        self.assertEqual(self.ctrl.handled, [])

    def test_it_uses_the_same_command_list_as_the_app(self):
        """In Bob the command runner is the app's own (stream.run_command), which refuses anything not on the dashboard list."""
        import stream
        self.assertNotIn("quit", stream.DASH_COMMANDS)
        self.assertNotIn("update", stream.DASH_COMMANDS)
        self.assertNotIn("pair", stream.DASH_COMMANDS)


class FakeServer:
    """Stands in for the `bless` Bluetooth server."""

    def __init__(self, name, loop):
        self.name, self.loop = name, loop
        self.chars, self.sent, self.started, self.stopped = {}, [], False, False
        self.read_request_func = self.write_request_func = None

    async def add_new_service(self, uuid):
        self.service = uuid

    async def add_new_characteristic(self, service, uuid, props, value, perms):
        self.chars[uuid] = SimpleNamespace(value=value, uuid=uuid)

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    def get_characteristic(self, uuid):
        return self.chars[uuid]

    def update_value(self, service, uuid):
        self.sent.append(bytes(self.chars[uuid].value))
        return True


class OverTheRadio(CoreCase):
    def start(self):
        self.server = None

        def factory(name, loop):
            self.server = FakeServer(name, loop)
            return self.server
        self.link = blelink.BleLink(self.core, "Lyra the Great", server_factory=factory, properties=(1, 2, 3, 4))
        self.link.start()
        end = time.time() + 3
        while not (self.link.running and self.server) and time.time() < end:
            time.sleep(0.01)
        self.addCleanup(self.finish)
        self.assertTrue(self.link.running, self.link.error)

    def finish(self):
        self.link.stop()
        self.link.join(3)

    def write(self, text):
        for piece in blecodec.chunks(text):
            self.server.loop.call_soon_threadsafe(self.server.write_request_func, self.server.chars[blecodec.RX], bytearray(piece))

    def heard(self, until=2.0):
        end = time.time() + until
        while time.time() < end:
            data = b"".join(self.server.sent).decode()
            if "\n" in data:
                return data
            time.sleep(0.01)
        return b"".join(self.server.sent).decode()

    def test_it_advertises_a_short_name_with_the_two_characteristics(self):
        self.start()
        self.assertEqual(self.server.name, "Lyra the")                  # a Bluetooth name has to be short
        self.assertEqual(set(self.server.chars), {blecodec.RX, blecodec.TX})
        self.assertEqual(self.server.service, blecodec.SERVICE)

    def test_hello_and_a_drive_pulse_work_through_small_packets(self):
        self.start()
        self.write(f"H {self.dev}")
        self.assertEqual(self.heard(), f"N {NONCE}\n")
        self.write(self.signed("D", "D 0.40 0.40"))
        end = time.time() + 2
        while not self.ctrl.moves and time.time() < end:
            time.sleep(0.01)
        self.assertEqual(self.ctrl.moves, [(0.4, 0.4, 0.4)])

    def test_a_long_answer_is_sent_in_packets_that_fit(self):
        self.start()
        self.core.run_command = lambda text, by=None: "a long line " * 5
        self.write(f"H {self.dev}")
        self.heard()
        self.server.sent.clear()
        self.write(self.signed("C", "C /usage"))
        data = self.heard()
        self.assertTrue(data.startswith("R a long line"))
        self.assertTrue(all(len(p) <= blecodec.CHUNK for p in self.server.sent))

    def test_the_emergency_stop_works_over_the_radio(self):
        self.start()
        self.write("E")
        end = time.time() + 2
        while not self.ctrl.estops and time.time() < end:
            time.sleep(0.01)
        self.assertEqual(self.ctrl.estops, ["bluetooth"])

    def test_it_stops_cleanly(self):
        self.start()
        self.link.stop()
        self.link.join(3)
        self.assertFalse(self.link.is_alive())
        self.assertTrue(self.server.stopped)

    def test_without_the_bless_package_it_says_so_and_does_not_crash(self):
        saved = sys.modules.get("bless", "missing")
        sys.modules["bless"] = None                                    # makes "import bless" fail
        self.addCleanup(lambda: sys.modules.pop("bless", None) if saved == "missing" else sys.modules.__setitem__("bless", saved))
        link = blelink.BleLink(self.core, "Bob")
        link.run()                                                     # synchronously: it must return, not raise
        self.assertFalse(link.running)
        self.assertTrue(link.error)


class TheKeyIsGivenOverTheNetwork(unittest.TestCase):
    """The app asks for its Bluetooth key while it is paired over Wi-Fi, at home, before the event."""

    def setUp(self):
        import stream
        from tests.test_appapi import client_proof  # noqa: F401
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        cfg = config.StreamConfig()
        cfg.host, cfg.port, cfg.https_port, cfg.bonjour = "127.0.0.1", 0, 0, False
        self.srv = stream.StreamServer(cfg, SimpleNamespace(capture_jpeg=lambda: b"x"), base=Path(self.tmp.name))
        full = config.Config()
        full.ble.enabled = True
        full.robot.name = "Lyra"
        self.srv.controller = SimpleNamespace(cfg=full, handle=lambda *a, **k: "", manual=lambda *a: "", drive=SimpleNamespace(stop=lambda: None))
        self.srv.status = lambda: {}
        self.srv.start()
        self.addCleanup(self.srv.stop)
        self.port = self.srv._httpsd.server_address[1]
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname, self.ctx.verify_mode = False, ssl.CERT_NONE

    def call(self, method, path, token=None):
        c = http.client.HTTPSConnection("127.0.0.1", self.port, timeout=5, context=self.ctx)
        h = {"Content-Type": "application/json"}
        if token:
            h["Authorization"] = f"Bearer {token}"
        c.request(method, path, b"{}", h)
        r = c.getresponse()
        data = json.loads(r.read() or b"{}")
        c.close()
        return r.status, data

    def paired(self, name="Test Mac"):
        ident, token = self.srv.devices.add(name)
        return ident, token

    def test_a_paired_device_gets_its_key_and_the_way_to_use_it(self):
        ident, token = self.paired()
        status, body = self.call("POST", "/api/v1/ble", token)
        self.assertEqual(status, 200)
        self.assertEqual(len(body["key"]), 64)
        self.assertEqual(body["device"], blecodec.short_id(ident))
        self.assertEqual((body["service"], body["rx"], body["tx"]), (blecodec.SERVICE, blecodec.RX, blecodec.TX))
        self.assertEqual((body["enabled"], body["name"]), (True, "Lyra"))
        self.assertEqual(self.call("POST", "/api/v1/ble", token)[1]["key"], body["key"])        # the same key every time

    def test_every_device_has_its_own_key_and_it_is_kept_in_devices_json_only_for_that_device(self):
        a = self.call("POST", "/api/v1/ble", self.paired("A")[1])[1]["key"]
        b = self.call("POST", "/api/v1/ble", self.paired("B")[1])[1]["key"]
        self.assertNotEqual(a, b)
        saved = json.loads((Path(self.tmp.name) / "devices.json").read_text())["devices"]
        self.assertEqual({saved["A"]["ble_key"], saved["B"]["ble_key"]}, {a, b})
        self.assertEqual(oct(os.stat(Path(self.tmp.name) / "devices.json").st_mode & 0o777), "0o600")

    def test_it_needs_a_login_and_a_paired_device(self):
        self.assertEqual(self.call("POST", "/api/v1/ble")[0], 401)
        self.assertEqual(self.call("POST", "/api/v1/ble", "not-a-token")[0], 401)

    def test_two_requests_in_a_row_on_one_connection_both_work(self):
        """The first version of the endpoint left its request body unread, which spoiled the next request on the same connection."""
        _, token = self.paired("Keeper")
        c = http.client.HTTPSConnection("127.0.0.1", self.port, timeout=5, context=self.ctx)
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
        for path in ("/api/v1/ble", "/api/v1/ble", "/api/v1/status"):
            c.request("POST" if "ble" in path else "GET", path, b"{}" if "ble" in path else None, headers)
            r = c.getresponse()
            r.read()
            self.assertEqual(r.status, 200, path)
        c.close()

    def test_unpairing_takes_the_key_with_it(self):
        ident, token = self.paired()
        self.call("POST", "/api/v1/ble", token)
        self.assertIsNotNone(self.srv.devices.ble_lookup(blecodec.short_id(ident)))
        self.srv.devices.remove(ident)
        self.assertIsNone(self.srv.devices.ble_lookup(blecodec.short_id(ident)))


class OnTheController(unittest.TestCase):
    def make(self, enabled):
        import bob
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        cfg = config.Config()
        cfg.stream.enabled = True
        cfg.stream.host, cfg.stream.port, cfg.stream.https, cfg.stream.bonjour = "127.0.0.1", 0, False, False
        cfg.ble.enabled = enabled
        c = bob.Controller(cfg, sim=True, paused=True)
        self.addCleanup(c.shutdown)
        return c

    def test_off_by_default_and_the_command_says_so(self):
        c = self.make(False)
        self.assertIsNone(c.ble)
        self.assertIn("Bluetooth control is off", c.handle("/ble"))

    def test_on_it_is_built_from_the_apps_own_device_list_and_command_runner(self):
        c = self.make(True)
        self.assertIsNotNone(c.ble)
        self.assertIs(c.ble.core.devices, c.stream.devices)
        self.assertEqual(c.ble.core.run_command.__func__, c.stream.run_command.__func__)
        self.assertIn("Bluetooth control", c.handle("/ble"))

    def test_a_real_controller_obeys_signed_drive_stop_and_the_emergency_stop(self):
        c = self.make(True)
        core = c.ble.core
        ident, _ = c.stream.devices.add("Test phone")
        key = c.stream.devices.ble_key(ident)
        dev = blecodec.short_id(ident)
        core._nonce = lambda: NONCE
        self.assertEqual(core.handle(f"H {dev}"), [f"N {NONCE}"])
        sig = blecodec.mac(key, dev, NONCE, 1, "D 0.50 0.50")
        self.assertEqual(core.handle(f"D {dev} 1 0.50 0.50 {sig}"), [])
        self.assertTrue(c.drive.moving)
        sig = blecodec.mac(key, dev, NONCE, 2, "S")
        self.assertEqual(core.handle(f"S {dev} 2 {sig}"), ["OK"])
        self.assertFalse(c.drive.moving)
        self.assertEqual(core.handle("E"), ["OK stopped"])
        self.assertTrue(c.drive.estop.is_set())
        sig = blecodec.mac(key, dev, NONCE, 3, "D 0.50 0.50")
        self.assertIn("E-stop", core.handle(f"D {dev} 3 0.50 0.50 {sig}")[0])         # and he will not move again until /clear
        self.assertFalse(c.drive.moving)

    def test_a_signed_command_cannot_do_what_the_app_may_not(self):
        c = self.make(True)
        core = c.ble.core
        ident, _ = c.stream.devices.add("Test phone")
        key = c.stream.devices.ble_key(ident)
        dev = blecodec.short_id(ident)
        core._nonce = lambda: NONCE
        core.handle(f"H {dev}")
        for n, text in enumerate(("/quit", "/update confirm", "/pair", "/set drive.left_invert true"), start=1):
            sig = blecodec.mac(key, dev, NONCE, n, f"C {text}")
            out = core.handle(f"C {dev} {n} {sig} {text}")
            self.assertTrue(out and "isn't available" in out[0], (text, out))

    def test_claude_has_no_way_to_use_it(self):
        import brain
        names = {t["name"] for t in brain.build_tools(3.0, colors=True, mecanum=True)}
        self.assertFalse({n for n in names if "ble" in n or "bluetooth" in n.lower()})


class TheCheckTool(CoreCase):
    """tools/ble_check.py builds its messages with the same signing as Bob: what it sends, Bob accepts."""

    def test_what_the_tool_builds_is_what_bob_accepts(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
        import ble_check
        self.assertEqual(self.hello(), [f"N {NONCE}"])
        self.assertEqual(self.core.handle(ble_check.build(self.dev, self.key, NONCE, 1, "T"))[0][:2], "T ")
        self.assertEqual(self.core.handle(ble_check.build(self.dev, self.key, NONCE, 2, "D", "0.30 0.30")), [])
        self.assertEqual(self.ctrl.moves, [(0.3, 0.3, 0.4)])
        self.assertEqual(self.core.handle(ble_check.build(self.dev, self.key, NONCE, 3, "S")), ["OK"])
        self.core.run_command = lambda text, by=None: "fine"
        self.assertEqual(self.core.handle(ble_check.build(self.dev, self.key, NONCE, 4, "C", "/usage")), ["R fine"])


class TheSetting(unittest.TestCase):
    def test_defaults_and_loading(self):
        c = config.BleConfig()
        self.assertEqual((c.enabled, c.open_estop, c.max_per_second), (False, True, 20.0))
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "config.toml"
            p.write_text("[ble]\nenabled = true\nopen_estop = false\n")
            cfg = config.load(p)
            self.assertEqual((cfg.ble.enabled, cfg.ble.open_estop), (True, False))
            p.write_text("[ble]\nenabld = true\n")
            with self.assertRaises(ValueError):
                config.load(p)


if __name__ == "__main__":
    unittest.main()
