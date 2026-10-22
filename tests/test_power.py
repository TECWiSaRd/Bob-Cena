"""Checks for /shutdown (powering the Pi off). Nothing here can power off a real computer. Run:  python3 -m unittest discover -s tests"""
import http.client
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from power import PowerControl  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def wait_for(cond, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class PowerUnit(unittest.TestCase):
    def make(self, sudo_ok=True, root=False, sim=False, **cfg):
        self.calls = []
        self.clock = Clock()

        def run(args, timeout=10):
            self.calls.append(args)
            return (0, "ok") if (sudo_ok or args[:2] != ["sudo", "-n"] or args[2] != "-l") and not (
                args[:3] == ["sudo", "-n", "-l"] and not sudo_ok) else (1, "a password is required")

        return PowerControl(config.PowerConfig(**cfg), sim=sim, run=run, which=lambda n: "/usr/sbin/shutdown",
                            clock=self.clock, euid=lambda: 0 if root else 1000)

    def test_roles(self):
        p = self.make()
        self.assertTrue(all(p.allows(r) for r in ("owner", "operator")))
        self.assertFalse(p.allows("dashboard"))                              # opt-in: guests' tokens can't power the Pi off
        self.assertTrue(self.make(who=["dashboard"]).allows("dashboard"))
        self.assertFalse(p.allows("viewer"))                       # watch-only users can't, unless the owner adds them
        self.assertTrue(self.make(who=["viewer"]).allows("viewer"))
        self.assertFalse(self.make(enabled=False).allows("owner"))

    def test_two_steps_by_the_same_person(self):
        p = self.make()
        self.assertFalse(p.confirm("kai")[0])                      # confirming without asking first does nothing
        self.assertIn("OFF", p.request("kai"))
        self.assertFalse(p.confirm("sam")[0])                      # someone else can't confirm kai's request
        self.assertTrue(p.confirm("kai")[0])
        self.assertTrue(p.requested)
        self.assertFalse(p.confirm("kai")[0])                      # and a request is used up once

    def test_the_window_closes(self):
        p = self.make(confirm_seconds=30)
        p.request("kai")
        self.clock.t += 31
        self.assertFalse(p.confirm("kai")[0])
        self.assertFalse(p.requested)

    def test_cancel(self):
        p = self.make()
        p.request("kai")
        self.assertEqual(p.cancel("kai"), "cancelled")
        self.assertFalse(p.confirm("kai")[0])
        self.assertEqual(p.cancel("kai"), "nothing to cancel")

    def test_without_permission_nothing_is_queued(self):
        p = self.make(sudo_ok=False)
        text = p.request("kai")
        self.assertIn("install_power.sh", text)
        self.assertFalse(p.confirm("kai")[0])

    def test_the_command_uses_sudo_without_a_password_unless_root(self):
        self.assertEqual(self.make().command(), ["sudo", "-n", "/usr/sbin/shutdown", "-h", "now"])
        self.assertEqual(self.make(root=True).command(), ["/usr/sbin/shutdown", "-h", "now"])

    def test_it_checks_sudo_without_running_the_shutdown(self):
        p = self.make()
        self.assertTrue(p.capable()[0])
        self.assertEqual(self.calls, [["sudo", "-n", "-l", "/usr/sbin/shutdown", "-h", "now"]])

    def test_execute_runs_the_command_only_after_a_confirmed_request(self):
        p = self.make()
        self.assertFalse(p.execute()[0])
        self.assertNotIn(["sudo", "-n", "/usr/sbin/shutdown", "-h", "now"], self.calls)
        p.request("kai")
        p.confirm("kai")
        self.assertTrue(p.execute()[0])
        self.assertEqual(self.calls[-1], ["sudo", "-n", "/usr/sbin/shutdown", "-h", "now"])

    def test_a_failed_power_off_is_reported(self):
        p = self.make()
        p.request("kai")
        p.confirm("kai")
        p._run = lambda args, timeout=10: (1, "boom")
        ok, text = p.execute()
        self.assertFalse(ok)
        self.assertIn("boom", text)

    def test_simulation_never_runs_anything(self):
        p = self.make(sim=True)
        self.assertTrue(p.capable()[0])
        p.request("kai")
        p.confirm("kai")
        self.assertEqual(p.execute(), (True, "[sim] the Pi would power off now"))
        self.assertEqual(self.calls, [])


class ThroughTheRobot(unittest.TestCase):
    def setUp(self):
        import bob
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        cfg = config.Config()
        cfg.stream.enabled = False
        self.ctrl = bob.Controller(cfg, sim=True, paused=True)
        self.addCleanup(self.ctrl.shutdown)
        self.ctrl.power._run = lambda *a, **k: self.fail("a real command was run in simulation")
        from timeline import Timeline
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.ctrl.timeline = Timeline(config.TimelineConfig(enabled=True, thumbnails=False), Path(self.dir.name) / "tl")

    def test_nothing_happens_without_the_second_step(self):
        self.assertIn("/shutdown confirm", self.ctrl.handle("/shutdown"))
        time.sleep(0.2)
        self.assertFalse(self.ctrl.quit.is_set())
        self.assertFalse(self.ctrl.power.requested)

    def test_confirm_stops_bob_and_marks_the_power_off(self):
        self.ctrl.handle("/shutdown", by="kai", role="operator")
        text = self.ctrl.handle("/shutdown confirm", by="kai", role="operator")
        self.assertIn("Shutting down", text)
        self.assertTrue(wait_for(self.ctrl.quit.is_set))            # Bob is told to quit (main() then powers off)
        self.assertTrue(self.ctrl.power.requested)
        rows = [r for r in self.ctrl.timeline.recent(10) if r["kind"] == "power"]
        self.assertEqual((rows[0]["action"], rows[0]["by"]), ("shutdown", "kai"))

    def test_the_wrong_person_cannot_confirm(self):
        self.ctrl.handle("/shutdown", by="kai", role="operator")
        self.assertIn("type /shutdown first", self.ctrl.handle("/shutdown confirm", by="sam", role="operator"))
        time.sleep(0.2)
        self.assertFalse(self.ctrl.quit.is_set())

    def test_roles(self):
        for role, allowed in (("owner", True), ("operator", True), ("dashboard", False), ("viewer", False)):
            text = self.ctrl.handle("/shutdown", role=role)
            self.assertEqual("isn't allowed" not in text, allowed, role)

    def test_turned_off_in_config(self):
        self.ctrl.power.cfg.enabled = False
        self.assertIn("isn't allowed", self.ctrl.handle("/shutdown"))

    def test_cancel(self):
        self.ctrl.handle("/shutdown", by="kai")
        self.assertEqual(self.ctrl.handle("/shutdown cancel", by="kai"), "cancelled")
        self.assertIn("type /shutdown first", self.ctrl.handle("/shutdown confirm", by="kai"))

    def test_claude_has_no_way_to_do_it(self):
        names = {t["name"] for t in self.ctrl.brain.tools}
        self.assertFalse({n for n in names if "shut" in n or "power" in n or "reboot" in n})

    def test_check_has_a_line_for_it(self):
        import selfcheck
        rows = {name: (lv, d) for lv, name, d in selfcheck.run_checks(self.ctrl, Path("."))}
        self.assertEqual(rows["power off"][0], "ok")
        self.assertIn("owner, operator", rows["power off"][1])


class FakeController:
    def __init__(self):
        self.handled = []
        self.power = SimpleNamespace(allows=lambda role: role == "dashboard")
        self.drive = SimpleNamespace(estop=SimpleNamespace(is_set=lambda: False))

    def handle(self, text, by=None, role="owner"):
        self.handled.append((text, by, role))
        return "ok"


class Dashboard(unittest.TestCase):
    def setUp(self):
        import stream
        from access import AccessPolicy
        cfg = config.StreamConfig()
        cfg.host, cfg.port = "0.0.0.0", 0
        self.srv = stream.StreamServer(cfg, camera=SimpleNamespace(capture_jpeg=lambda: None),
                                       policy=AccessPolicy("owner-secret-1234", wifi_reader=lambda: None))
        self.srv.controller = FakeController()
        self.srv.start()
        self.addCleanup(self.srv._httpd.server_close)
        self.addCleanup(self.srv._httpd.shutdown)
        self.stream = stream

    def test_the_dashboard_may_send_it_with_its_role(self):
        self.assertIn("shutdown", self.stream.DASH_COMMANDS)
        port = self.srv._httpd.server_address[1]
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        body = json.dumps({"cmd": "/shutdown"}).encode()
        c.request("POST", "/api/cmd?token=owner-secret-1234", body, {"Content-Type": "application/json", "Content-Length": str(len(body))})
        self.assertEqual(c.getresponse().status, 200)
        self.assertEqual(self.srv.controller.handled, [("/shutdown", "owner", "dashboard")])

    def test_the_button_is_in_the_page_with_a_confirmation(self):
        page = self.stream.DASH_PAGE
        self.assertIn('id=poweroff', page)
        self.assertIn("confirm('Shut down the Pi?", page)
        self.assertIn("cmd('/shutdown');await cmd('/shutdown confirm')", page)


class InstallPower(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name)
        self.file = t / "bob-power"
        stubs = t / "stubs"
        stubs.mkdir()
        (stubs / "sudo").write_text('#!/bin/sh\nexec "$@"\n')
        (stubs / "visudo").write_text('#!/bin/sh\n[ -z "$VISUDO_FAIL" ] && grep -q "^[a-z][a-z0-9._-]* ALL=(root) NOPASSWD: /" "$3"\n')
        for p in stubs.iterdir():
            p.chmod(0o755)
        self.env = {**os.environ, "PATH": f"{stubs}:{os.environ['PATH']}", "BOB_SUDOERS_FILE": str(self.file),
                    "BOB_OWNER": "adam", "BOB_INSTALL_OWNER": "", "BOB_SHUTDOWN_PATH": "/usr/sbin/shutdown"}

    def run_script(self, *args, answer=None, env=None):
        return subprocess.run(["bash", str(ROOT / "install_power.sh"), *args], input=answer, text=True,
                              capture_output=True, env={**self.env, **(env or {})}, cwd=ROOT)

    def test_installs_exactly_one_narrow_rule(self):
        r = self.run_script("--yes")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = [l for l in self.file.read_text().splitlines() if not l.startswith("#")]
        self.assertEqual(lines, ["adam ALL=(root) NOPASSWD: /usr/sbin/shutdown -h now"])
        self.assertEqual(oct(self.file.stat().st_mode & 0o777), "0o440")

    def test_a_rule_that_fails_visudo_is_never_installed(self):
        r = self.run_script("--yes", env={"VISUDO_FAIL": "1"})
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(self.file.exists())
        self.assertIn("nothing was installed", r.stdout)

    def test_odd_account_names_are_refused(self):
        for bad in ("a b", "adam;rm", "x\\y", ""):
            r = self.run_script("--yes", env={"BOB_OWNER": bad})
            self.assertNotEqual(r.returncode, 0, bad)
        self.assertFalse(self.file.exists())

    def test_it_asks_first(self):
        r = self.run_script(answer="n\n")
        self.assertIn("Cancelled", r.stdout)
        self.assertIn("exactly", r.stdout)
        self.assertFalse(self.file.exists())

    def test_undo(self):
        self.run_script("--yes")
        self.assertEqual(self.run_script("--undo").returncode, 0)
        self.assertFalse(self.file.exists())


if __name__ == "__main__":
    unittest.main()


class DetachTests(unittest.TestCase):
    def setUp(self):
        import bob
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        cfg = config.Config()
        cfg.stream.enabled = False
        self.ctrl = bob.Controller(cfg, sim=True, paused=True)
        self.addCleanup(self.ctrl.shutdown)

    def test_outside_tmux_it_says_so_and_bob_keeps_running(self):
        old = os.environ.pop("TMUX", None)
        self.addCleanup(lambda: old and os.environ.__setitem__("TMUX", old))
        self.assertIn("isn't running inside tmux", self.ctrl.handle("/detach"))
        self.assertFalse(self.ctrl.quit.is_set())

    def test_inside_tmux_it_detaches_that_session_only(self):
        import subprocess
        from unittest import mock
        calls = []
        def fake(args, **k):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, stdout="bob\n", stderr="")
        with mock.patch.dict(os.environ, {"TMUX": "/tmp/tmux-1/default,1,0"}), mock.patch("subprocess.run", fake):
            self.assertEqual(self.ctrl.handle("/detach"), "")
        self.assertEqual(calls[-1], ["tmux", "detach-client", "-s", "bob"])
        self.assertFalse(self.ctrl.quit.is_set())

    def test_shared_console_users_cannot_detach_the_owner(self):
        self.assertIn("only works in the tmux console", self.ctrl.handle("/detach", by="kai", role="operator"))


class DriveScopeTests(unittest.TestCase):
    """/drive is for the person who typed it; /drive all is for everyone."""

    def setUp(self):
        import bob
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        cfg = config.Config()
        cfg.stream.enabled = False
        self.ctrl = bob.Controller(cfg, sim=True, paused=True)
        self.addCleanup(self.ctrl.shutdown)

    def test_drive_is_just_for_the_person_who_asked(self):
        self.ctrl.handle("/drive", by="kai", role="operator")
        self.assertTrue(self.ctrl.drive_mode)                       # Bob is under manual control...
        self.assertTrue(self.ctrl.driving_for("kai"))
        self.assertFalse(self.ctrl.driving_for("sam"))              # ...but Sam's and the owner's keyboards are unchanged
        self.assertFalse(self.ctrl.driving_for(None))

    def test_the_local_console_is_a_person_too(self):
        self.ctrl.handle("/drive")
        self.assertTrue(self.ctrl.driving_for(None))
        self.assertFalse(self.ctrl.driving_for("kai"))

    def test_drive_all_is_for_everyone_attached_right_now(self):
        self.ctrl.remote = SimpleNamespace(drivers=lambda: ["kai", "sam"])      # viewers are never in this list
        self.ctrl.handle("/drive all", by="kai", role="operator")
        self.assertTrue(all(self.ctrl.driving_for(w) for w in ("kai", "sam", None)))
        self.assertFalse(self.ctrl.driving_for("a-viewer"))

    def test_two_people_can_both_drive(self):
        self.ctrl.handle("/drive", by="kai", role="operator")
        self.ctrl.handle("/drive", by="sam", role="operator")
        self.assertTrue(self.ctrl.driving_for("kai") and self.ctrl.driving_for("sam"))
        self.ctrl.leave_drive("kai")
        self.assertFalse(self.ctrl.driving_for("kai"))
        self.assertTrue(self.ctrl.driving_for("sam") and self.ctrl.drive_mode)
        self.ctrl.leave_drive("sam")
        self.assertFalse(self.ctrl.drive_mode)                      # the last one out ends manual control

    def test_after_drive_all_one_person_leaving_leaves_the_others_driving(self):
        self.ctrl.remote = SimpleNamespace(drivers=lambda: ["kai", "sam"])
        self.ctrl.handle("/drive all")
        self.ctrl.leave_drive("kai")
        self.assertFalse(self.ctrl.driving_for("kai"))
        self.assertTrue(self.ctrl.driving_for("sam") and self.ctrl.driving_for(None) and self.ctrl.drive_mode)
        self.ctrl.handle("/drive", by="kai", role="operator")                  # and Kai can rejoin; nothing is swallowed
        self.assertTrue(self.ctrl.driving_for("kai"))

    def test_the_old_style_setter_cannot_leave_manual_drive_with_nobody_driving(self):
        self.ctrl.drive_mode = True
        self.assertTrue(self.ctrl.driving_for(None))
        self.ctrl.drive_mode = False
        self.assertFalse(self.ctrl.drive_mode)
        self.assertFalse(self.ctrl.driving_for(None))

    def test_many_threads_joining_and_leaving_never_raise(self):
        import threading as th
        errors = []
        def hammer(name):
            try:
                for i in range(300):
                    self.ctrl.join_drive(name, everyone=(i % 7 == 0))
                    self.ctrl.driving_for(name)
                    self.ctrl.leave_drive(name)
            except Exception as e:
                errors.append(e)
        threads = [th.Thread(target=hammer, args=(f"p{i}",)) for i in range(6)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(errors, [])

    def test_estop_and_resume_end_it_for_everyone(self):
        self.ctrl.handle("/drive all")
        self.ctrl.estop("test")
        self.assertFalse(self.ctrl.drive_mode)
        self.assertFalse(self.ctrl.driving_for("kai"))
        self.ctrl.handle("/clear")
        self.ctrl.handle("/drive", by="kai", role="operator")
        self.ctrl.handle("/resume")
        self.assertFalse(self.ctrl.drive_mode)

    def test_junk_argument_is_refused(self):
        self.assertIn("usage", self.ctrl.handle("/drive everybody"))
        self.assertFalse(self.ctrl.drive_mode)


class CheckInBackgroundTests(unittest.TestCase):
    def setUp(self):
        import bob
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        cfg = config.Config()
        cfg.stream.enabled = False
        self.bob = bob
        self.ctrl = bob.Controller(cfg, sim=True, paused=True)
        self.addCleanup(self.ctrl.shutdown)

    def test_a_slow_check_never_blocks_the_console(self):
        import threading as th
        gate, seen = th.Event(), []
        self.addCleanup(setattr, self.bob, "run_checks", self.bob.run_checks)
        self.bob.run_checks = lambda ctrl, base: (gate.wait(5), [("ok", "slow thing", "fine")])[1]
        handler = logging.Handler()
        handler.emit = lambda record: seen.append(record.getMessage())
        logging.getLogger("bob").addHandler(handler)
        self.addCleanup(logging.getLogger("bob").removeHandler, handler)
        logging.getLogger("bob").setLevel(logging.INFO)
        t0 = time.monotonic()
        self.assertIn("checking", self.ctrl.handle("/check"))
        self.assertLess(time.monotonic() - t0, 0.5)                             # the console is free again at once
        self.assertIn("already running", self.ctrl.handle("/check"))
        gate.set()
        end = time.monotonic() + 3
        while not any("slow thing" in m for m in seen) and time.monotonic() < end:
            time.sleep(0.02)
        self.assertTrue(any("slow thing" in m for m in seen))                    # the report arrives in the log
        time.sleep(0.1)
        self.assertIn("checking", self.ctrl.handle("/check"))                    # and it can be run again


import logging  # noqa: E402
