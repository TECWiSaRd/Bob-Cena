"""Checks for the shared console. Real local sockets, a pretend operating system (who is who). Run:  python3 -m unittest discover -s tests"""
import json
import logging
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import remote  # noqa: E402
from console import ConsoleUI, LogBuffer  # noqa: E402
from remote import RemoteConsole, RemoteController, encode  # noqa: E402

OWNER_UID = os.getuid()


def wait_for(cond, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


class FakeCtrl:
    def __init__(self):
        self.handled, self.manual_moves, self.estops, self.stops = [], [], [], 0
        self.drive_mode = False
        self.drive = SimpleNamespace(estop=threading.Event(), stop=self._stop)
        self.viewers_may_power_off = False
        self.power = SimpleNamespace(allows=lambda role: role != "viewer" or self.viewers_may_power_off)
        self.listener = SimpleNamespace(ptt_toggle=lambda: "recording")

    def _stop(self):
        self.stops += 1

    def handle(self, line, by=None, role="owner"):
        self.handled.append((line, by))
        self.roles = getattr(self, "roles", []) + [role]
        return "ok: " + line if line.startswith("/say") else None

    def manual(self, l, r, s, blocking=False):
        self.manual_moves.append((l, r))

    def estop(self, source="console"):
        self.estops.append(source)
        self.drive.estop.set()

    def status_line(self):
        return f" BOB  AUTO | estop={self.drive.estop.is_set()}"


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir="/tmp")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, "c.sock")
        self.cfg = config.RemoteConfig(enabled=True, socket=self.path)
        self.ctrl = FakeCtrl()
        self.logbuf = LogBuffer()
        self.logbuf.setFormatter(logging.Formatter("%(message)s"))
        self.logger = logging.getLogger("bob")
        self.old_level = self.logger.level
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(self.logbuf)
        self.addCleanup(self.logger.removeHandler, self.logbuf)
        self.addCleanup(self.logger.setLevel, self.old_level)
        self.identity = (OWNER_UID + 1, "alex", {"bobops"})                  # who the pretend OS says is connecting
        self.server = RemoteConsole(self.cfg, self.ctrl, self.logbuf, identify=lambda conn: self.identity)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.clients = []

    def connect(self, identity=None, owner_uid=None):
        if identity is not None:
            self.identity = identity
        c = RemoteController(self.path, owner_uid)
        self.clients.append(c)
        self.addCleanup(lambda: c.sock.close())
        wait_for(lambda: c.user != "?" or not c.connected)        # the server has decided who this is
        return c

    def says(self, client, text):
        return any(text in line for _, _, line in list(client.log.lines))

    # ---- who may do what ----------------------------------------------------------------------------------
    def test_operator_sees_the_log_runs_commands_and_is_named(self):
        logging.getLogger("bob.test").info("BOB  hello from before")
        c = self.connect()
        self.assertTrue(wait_for(lambda: c.user == "alex"))
        self.assertTrue(wait_for(lambda: self.says(c, "hello from before")))      # the backlog
        logging.getLogger("bob.test").info("BOB  something new")
        self.assertTrue(wait_for(lambda: self.says(c, "something new")))          # the live stream
        c.handle("/say hi")
        self.assertTrue(wait_for(lambda: self.ctrl.handled == [("/say hi", "alex")]))
        self.assertTrue(wait_for(lambda: self.says(c, "ok: /say hi")))             # the answer arrives in the log
        self.assertIn("alex (operator)", c.status_line())

    def test_everyone_sees_everyones_commands(self):
        a = self.connect((OWNER_UID + 1, "alex", {"bobops"}))
        b = self.connect((OWNER_UID + 2, "kai", {"bobview"}))
        a.handle("/say hello")
        self.assertTrue(wait_for(lambda: self.says(b, "> [alex] /say hello")))

    def test_viewers_can_watch_and_stop_but_not_command(self):
        v = self.connect((OWNER_UID + 2, "kai", {"bobview"}))
        v.handle("/fwd 1")
        self.assertTrue(wait_for(lambda: self.says(v, "view-only")))
        v.manual(1, 1, 0.6)
        v.listener.ptt_toggle()
        time.sleep(0.2)
        self.assertEqual((self.ctrl.handled, self.ctrl.manual_moves), ([], []))
        v.estop()
        self.assertTrue(wait_for(lambda: len(self.ctrl.estops) == 1))
        self.assertIn("kai", self.ctrl.estops[0])
        self.assertTrue(wait_for(lambda: v.drive.estop.is_set()))                  # and the status bar shows it
        self.assertIn("view only", v.status_line())

    def test_viewers_may_power_off_only_if_the_owner_allows_it(self):
        v = self.connect((OWNER_UID + 2, "kai", {"bobview"}))
        v.handle("/shutdown")
        self.assertTrue(wait_for(lambda: self.says(v, "view-only")))
        self.assertEqual(self.ctrl.handled, [])
        self.ctrl.viewers_may_power_off = True
        v.handle("/shutdown")
        self.assertTrue(wait_for(lambda: ("/shutdown", "kai") in self.ctrl.handled))
        v.handle("/fwd 1")                                          # but nothing else
        time.sleep(0.2)
        self.assertEqual(self.ctrl.handled, [("/shutdown", "kai")])
        self.assertEqual(self.ctrl.roles, ["viewer"])

    def test_the_role_reaches_the_controller(self):
        op = self.connect((OWNER_UID + 1, "alex", {"bobops"}))
        op.handle("/say hi")
        self.assertTrue(wait_for(lambda: self.ctrl.handled))
        self.assertEqual(self.ctrl.roles, ["operator"])

    def test_strangers_are_refused_with_a_reason(self):
        c = self.connect((OWNER_UID + 3, "mallory", {"users"}))
        self.assertTrue(wait_for(lambda: self.says(c, "isn't allowed")))
        self.assertFalse(wait_for(lambda: c.connected, 0.3))
        self.assertEqual(self.ctrl.handled, [])
        self.assertTrue(any("refused mallory" in l for _, _, l in self.logbuf.lines))

    def test_unidentifiable_peers_are_refused(self):
        self.server._identify = lambda conn: None
        c = self.connect()
        self.assertTrue(wait_for(lambda: self.says(c, "isn't allowed")))

    def test_deny_list_blocks_quit_for_everyone_but_the_owner(self):
        op = self.connect((OWNER_UID + 1, "alex", {"bobops"}))
        op.handle("/quit")
        self.assertTrue(wait_for(lambda: self.says(op, "only for the owner")))
        self.assertEqual(self.ctrl.handled, [])
        owner = self.connect((OWNER_UID, "adam", set()))
        owner.handle("/quit")
        self.assertTrue(wait_for(lambda: ("/quit", "adam") in self.ctrl.handled))

    def test_deny_list_is_case_and_spacing_proof(self):
        op = self.connect()
        op.handle("/QUIT")
        op.handle("/quit now")
        time.sleep(0.2)
        self.assertEqual(self.ctrl.handled, [])

    def test_manual_driving_only_in_drive_mode_and_clamped(self):
        c = self.connect()
        c.manual(1, 1, 0.6)
        time.sleep(0.2)
        self.assertEqual(self.ctrl.manual_moves, [])
        self.ctrl.drive_mode = True
        c.manual(9, -9, 0.6)
        self.assertTrue(wait_for(lambda: self.ctrl.manual_moves == [(1.0, -1.0)]))
        c.drive_mode = False                                                       # leaving drive mode
        self.assertTrue(wait_for(lambda: self.ctrl.drive_mode is False))
        self.assertGreaterEqual(self.ctrl.stops, 1)

    def test_status_updates_reach_the_client(self):
        c = self.connect()
        self.assertTrue(wait_for(lambda: "estop=False" in c.status_line()))
        self.ctrl.drive.estop.set()
        self.assertTrue(wait_for(lambda: "estop=True" in c.status_line()))

    # ---- robustness -----------------------------------------------------------------------------------------
    def test_garbage_and_oversize_messages_do_no_harm(self):
        c = self.connect()
        raw = c.sock
        raw.sendall(b"this is not json\n[1,2,3]\n\n")
        raw.sendall(b'{"type":"line","text":"' + b"x" * 5000 + b'"}\n')
        raw.sendall(encode({"type": "no-such-thing"}))
        raw.sendall(encode({"type": "line", "text": "/say still works"}))
        self.assertTrue(wait_for(lambda: ("/say still works", "alex") in self.ctrl.handled))
        self.assertEqual(len(self.ctrl.handled), 1)

    def test_a_flood_is_rate_limited(self):
        c = self.connect()
        for _ in range(500):
            c.sock.sendall(encode({"type": "line", "text": "/say spam"}))
        time.sleep(0.5)
        self.assertLess(len(self.ctrl.handled), 250)

    def test_endless_data_without_newlines_drops_the_connection(self):
        c = self.connect()
        try:
            for _ in range(20):
                c.sock.sendall(b"a" * 4096)
        except OSError:
            pass
        self.assertTrue(wait_for(lambda: self.server.clients == []))

    def test_too_many_clients(self):
        for i in range(self.cfg.max_clients):
            self.connect((OWNER_UID + 1, f"u{i}", {"bobops"}))
        self.assertTrue(wait_for(lambda: len(self.server.clients) == self.cfg.max_clients))
        extra = self.connect()
        self.assertTrue(wait_for(lambda: self.says(extra, "too many")))

    def test_who_lists_people_and_forgets_them_when_they_leave(self):
        a = self.connect((OWNER_UID + 1, "alex", {"bobops"}))
        self.assertTrue(wait_for(lambda: "alex (operator)" in self.server.describe()))
        a.sock.close()
        self.assertTrue(wait_for(lambda: "nobody attached" in self.server.describe()))

    def test_a_slow_client_never_blocks_the_others(self):
        slow = self.connect()
        slow.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
        slow._read = lambda: None
        fast = self.connect((OWNER_UID + 2, "kai", {"bobops"}))
        for i in range(3000):
            logging.getLogger("bob.test").info("BOB  line %d %s", i, "x" * 200)
        self.assertTrue(wait_for(lambda: self.says(fast, "line 2999"), 10))

    def test_stopping_the_server_removes_the_socket_and_disconnects_clients(self):
        c = self.connect()
        self.assertTrue(wait_for(lambda: c.user == "alex"))
        self.server.stop()
        self.assertTrue(wait_for(lambda: not c.connected))
        self.assertFalse(os.path.exists(self.path))

    # ---- the socket file ------------------------------------------------------------------------------------
    def test_socket_is_open_to_connect_but_not_to_act(self):
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o666)

    def test_client_refuses_a_socket_owned_by_someone_else(self):
        with self.assertRaises(ConnectionError):
            RemoteController(self.path, owner_uid=OWNER_UID + 12345)

    def test_stale_socket_is_replaced_but_a_live_one_or_a_plain_file_is_not(self):
        self.server.stop()
        stale = socket.socket(socket.AF_UNIX)
        stale.bind(self.path)
        stale.close()                                             # a leftover file nobody listens on
        again = RemoteConsole(self.cfg, self.ctrl, self.logbuf, identify=lambda c: None)
        again.start()
        self.addCleanup(again.stop)
        self.assertEqual(again.problem, "")
        second = RemoteConsole(self.cfg, self.ctrl, self.logbuf, identify=lambda c: None)
        second.start()
        self.assertIn("already using", second.problem)
        again.stop()
        Path(self.path).write_text("not a socket")
        third = RemoteConsole(self.cfg, self.ctrl, self.logbuf, identify=lambda c: None)
        third.start()
        self.assertIn("something else", third.problem)
        self.assertEqual(Path(self.path).read_text(), "not a socket")      # and it was left alone

    def test_disabled_does_nothing(self):
        path = os.path.join(self.dir, "off.sock")
        off = RemoteConsole(config.RemoteConfig(enabled=False, socket=path), self.ctrl, self.logbuf)
        off.start()
        self.assertFalse(os.path.exists(path))
        self.assertEqual(off.describe(), "off")

    def test_without_linux_peer_credentials_it_refuses_to_start(self):
        old = remote.PEERCRED
        remote.PEERCRED = None
        try:
            path = os.path.join(self.dir, "nolinux.sock")
            server = RemoteConsole(config.RemoteConfig(enabled=True, socket=path), self.ctrl, self.logbuf)
            server.start()
            self.assertIn("needs Linux", server.problem)
            self.assertFalse(os.path.exists(path))
        finally:
            remote.PEERCRED = old

    # ---- the real screen code on top of the remote controller ----------------------------------------------------
    def test_console_keys_work_through_the_remote_controller(self):
        c = self.connect()
        ui = object.__new__(ConsoleUI)                              # the screen code without a terminal
        ui.ctrl, ui.logbuf, ui.scr = c, c.log, SimpleNamespace(getmaxyx=lambda: (30, 100))
        ui.buf, ui.scroll, ui.history, ui.hist_idx = "", 0, [], 0
        for ch in "/say typed":
            ui.edit_key(ch)
        ui.edit_key("\n")
        self.assertTrue(wait_for(lambda: ("/say typed", "alex") in self.ctrl.handled))
        ui.edit_key(" ")                                           # Space on an empty line is the emergency stop
        self.assertTrue(wait_for(lambda: len(self.ctrl.estops) == 1))
        ui.edit_key("\t")                                          # Tab is push-to-talk
        self.ctrl.drive_mode = True
        self.assertTrue(wait_for(lambda: c.drive_mode))
        ui.drive_key("w")
        self.assertTrue(wait_for(lambda: self.ctrl.manual_moves == [(1, 1)]))
        ui.drive_key("x")
        self.assertTrue(wait_for(lambda: self.ctrl.drive_mode is False))


class PeerIdentity(unittest.TestCase):
    """The Linux part can only be checked on Linux; this checks our reading of what the kernel returns."""

    def test_reads_the_kernels_answer(self):
        import getpass
        import grp
        import struct
        old = remote.PEERCRED
        remote.PEERCRED = 17
        try:
            conn = SimpleNamespace(getsockopt=lambda level, opt, size: struct.pack("iII", 4242, os.getuid(), os.getgid()))
            uid, name, groups = remote.peer_identity(conn)
            self.assertEqual((uid, name), (os.getuid(), getpass.getuser()))
            self.assertIn(grp.getgrgid(os.getgid()).gr_name, groups)
        finally:
            remote.PEERCRED = old

    def test_an_unknown_user_id_is_not_identified(self):
        import struct
        old = remote.PEERCRED
        remote.PEERCRED = 17
        try:
            conn = SimpleNamespace(getsockopt=lambda *a: struct.pack("iII", 1, 4000000000, 4000000000))
            self.assertIsNone(remote.peer_identity(conn))
        finally:
            remote.PEERCRED = old


class AttributionThroughTheRealController(unittest.TestCase):
    def setUp(self):
        import bob
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        cfg = config.Config()
        cfg.stream.enabled = False
        self.ctrl = bob.Controller(cfg, sim=True, paused=True)
        self.addCleanup(self.ctrl.shutdown)
        from timeline import Timeline
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.ctrl.timeline = Timeline(config.TimelineConfig(enabled=True, thumbnails=False), Path(self.dir.name) / "tl")

    def test_commands_and_messages_carry_the_persons_name(self):
        self.ctrl.handle("/speed 0.4", by="alex")
        self.ctrl.handle("hello Bob", by="alex")
        self.ctrl.handle("/ask are you there", by="kai")
        rows = self.ctrl.timeline.recent(20)
        self.assertIn(("operator_command", "alex"), {(r["kind"], r.get("by")) for r in rows})
        self.assertIn(("operator", "kai"), {(r["kind"], r.get("by")) for r in rows})
        inbox = self.ctrl.controls.take_inbox()
        self.assertEqual(inbox, ["[alex] hello Bob", "[kai] are you there"])

    def test_the_local_console_is_unchanged(self):
        self.ctrl.handle("hello Bob")
        self.assertEqual(self.ctrl.controls.take_inbox(), ["hello Bob"])
        self.assertEqual(self.ctrl.handle("/who"), "the shared console is off ([remote] enabled = true)")


if __name__ == "__main__":
    unittest.main()
