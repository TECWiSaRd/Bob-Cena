import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import version  # noqa: E402
from update import Updater  # noqa: E402

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main", "-c", "commit.gpgsign=false"]


def git(cwd, *args):
    return subprocess.run([*GIT, *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class RepoCase(unittest.TestCase):
    """A pretend GitHub (bare repo), a pretend Mac clone, and a pretend Pi checkout."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name)
        self.hub, self.mac, self.pi = t / "hub.git", t / "mac", t / "pi"
        git(t, "init", "--bare", str(self.hub))
        git(t, "clone", "-q", str(self.hub), str(self.mac))
        (self.mac / "good.py").write_text("X = 1\n")
        (self.mac / "requirements.txt").write_text("anthropic\n")
        git(self.mac, "add", "."), git(self.mac, "commit", "-qm", "first")
        git(self.mac, "push", "-q", "origin", "HEAD:main")
        git(t, "clone", "-q", "-b", "main", str(self.hub), str(self.pi))
        self.up = Updater(self.pi)

    def push(self, name, text, message):
        (self.mac / name).write_text(text)
        git(self.mac, "add", "."), git(self.mac, "commit", "-qm", message)
        git(self.mac, "push", "-q", "origin", "HEAD:main")


class UpdaterTests(RepoCase):
    def test_up_to_date(self):
        ok, text, behind = self.up.status()
        self.assertEqual((ok, behind), (True, 0))
        self.assertIn("up to date", text)

    def test_it_lists_what_is_new_and_installs_it(self):
        self.push("good.py", "X = 2\n", "Make X two")
        ok, text, behind = self.up.status()
        self.assertEqual(behind, 1)
        self.assertIn("Make X two", text)
        self.assertEqual((self.pi / "good.py").read_text(), "X = 1\n")          # looking changed nothing
        ok, text, changed = self.up.apply()
        self.assertEqual((ok, changed), (True, True))
        self.assertEqual((self.pi / "good.py").read_text(), "X = 2\n")
        self.assertIn("Make X two", text)

    def test_a_syntax_error_is_rolled_back(self):
        before = git(self.pi, "rev-parse", "HEAD")
        self.push("broken.py", "def oops(:\n", "Add a broken file")
        ok, text, changed = self.up.apply()
        self.assertEqual((ok, changed), (False, False))
        self.assertIn("broken.py", text)
        self.assertEqual(git(self.pi, "rev-parse", "HEAD"), before)             # the old code is back
        self.assertFalse((self.pi / "broken.py").exists())

    def test_files_changed_by_hand_are_never_overwritten(self):
        (self.pi / "good.py").write_text("X = 99  # my own edit\n")
        self.push("other.py", "Y = 1\n", "Add other")
        self.assertIn("changed by hand", self.up.status()[1])
        ok, text, changed = self.up.apply()
        self.assertEqual((ok, changed), (False, False))
        self.assertEqual((self.pi / "good.py").read_text(), "X = 99  # my own edit\n")

    def test_untracked_pi_files_do_not_block_an_update(self):
        (self.pi / "memory.json").write_text("[]")
        (self.pi / ".env").write_text("SECRET=1\n")
        self.push("good.py", "X = 3\n", "Bump")
        ok, _, changed = self.up.apply()
        self.assertTrue(ok and changed)
        self.assertEqual((self.pi / ".env").read_text(), "SECRET=1\n")

    def test_changed_requirements_are_installed(self):
        calls = []

        def run(args, cwd, timeout=120):
            if args[0] != "git":
                calls.append(args)                                  # pretend pip worked; never install anything for real
                return 0, ""
            done = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
            return done.returncode, (done.stdout + done.stderr).strip()

        self.push("requirements.txt", "anthropic\nnewpkg\n", "New dependency")
        ok, _, changed = Updater(self.pi, run=run).apply()
        self.assertTrue(ok and changed)
        self.assertTrue(any("pip" in a for a in calls[0]))

    def test_no_network_or_bad_remote_is_explained(self):
        git(self.pi, "remote", "set-url", "origin", str(Path(self.tmp.name) / "nowhere.git"))
        ok, text, _ = self.up.status()
        self.assertFalse(ok)
        self.assertIn("couldn't reach GitHub", text)

    def test_a_non_git_copy_explains_how_to_enable_updates(self):
        plain = Path(self.tmp.name) / "plain"
        plain.mkdir()
        ok, text, _ = Updater(plain).status()
        self.assertFalse(ok)
        self.assertIn("setup_updates.sh", text)
        self.assertFalse(Updater(plain).apply()[0])


class VersionTests(unittest.TestCase):
    def test_hash_changes_when_a_file_changes(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a.py").write_text("1")
            h = version.code_hash(d)
            self.assertEqual(h, version.code_hash(d))
            (Path(d) / "a.py").write_text("2")
            self.assertNotEqual(h, version.code_hash(d))

    def test_the_client_and_server_agree_on_the_console_fingerprint(self):
        import remote
        self.assertEqual(remote.my_files_hash(), version.console_hash(Path(remote.__file__).resolve().parent))

    def test_describe_in_a_git_checkout_and_in_a_plain_copy(self):
        self.assertIn("code ", version.describe(Path(__file__).resolve().parent.parent))
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "x.py").write_text("1")
            self.assertIn("not a git checkout", version.describe(d))


class CommandTests(RepoCase):
    def setUp(self):
        super().setUp()
        import bob
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        cfg = config.Config()
        cfg.stream.enabled = False
        self.ctrl = bob.Controller(cfg, sim=True, paused=True)
        self.addCleanup(self.ctrl.shutdown)
        self.ctrl.updater = Updater(self.pi)

    def wait_idle(self):
        end = time.monotonic() + 10
        while time.monotonic() < end:
            if self.ctrl._check_lock.acquire(blocking=False):
                self.ctrl._check_lock.release()
                return
            time.sleep(0.05)
        self.fail("update thread still running")

    def test_only_the_owner_may_update(self):
        for role in ("operator", "viewer", "dashboard"):
            self.assertIn("only the owner", self.ctrl.handle("/update", by="kai", role=role))

    def test_two_steps_and_a_restart_only_under_the_service(self):
        self.push("good.py", "X = 5\n", "Five")
        self.assertIn("type /update first", self.ctrl.handle("/update confirm"))
        self.ctrl.handle("/update")
        self.wait_idle()
        os.environ["BOB_SUPERVISED"] = "1"
        self.addCleanup(os.environ.pop, "BOB_SUPERVISED", None)
        self.assertIn("updating", self.ctrl.handle("/update confirm"))
        self.wait_idle()
        self.assertEqual((self.pi / "good.py").read_text(), "X = 5\n")
        self.assertTrue(self.ctrl.restart_requested and self.ctrl.quit.is_set())

    def test_started_by_hand_it_updates_but_does_not_quit(self):
        self.push("good.py", "X = 6\n", "Six")
        os.environ.pop("BOB_SUPERVISED", None)
        self.ctrl.handle("/update")
        self.wait_idle()
        self.ctrl.handle("/update confirm")
        self.wait_idle()
        self.assertEqual((self.pi / "good.py").read_text(), "X = 6\n")
        self.assertFalse(self.ctrl.quit.is_set())

    def test_nothing_new_means_no_confirm_window(self):
        self.ctrl.handle("/update")
        self.wait_idle()
        self.assertIn("type /update first", self.ctrl.handle("/update confirm"))

    def test_claude_has_no_way_to_update(self):
        names = {t["name"] for t in self.ctrl.brain.tools}
        self.assertFalse({n for n in names if "update" in n or "pull" in n})

    def test_version_command(self):
        self.assertIn("Bob 26.", self.ctrl.handle("/version"))


class SetupScriptTests(unittest.TestCase):
    script = Path(__file__).resolve().parent.parent / "setup_updates.sh"

    def run_script(self, *args):
        return subprocess.run(["bash", str(self.script), *args], capture_output=True, text=True, timeout=20)

    def test_valid_shell_with_help(self):
        subprocess.run(["bash", "-n", str(self.script)], check=True)
        self.assertIn("deploy key", self.run_script("--help").stdout)

    def test_bad_options_are_refused_before_anything_happens(self):
        self.assertEqual(self.run_script("--nonsense").returncode, 2)
        self.assertEqual(self.run_script("--repo", "justaname").returncode, 2)

    def test_an_existing_checkout_is_left_alone(self):
        with tempfile.TemporaryDirectory() as d:
            copy = Path(d) / "bob"
            copy.mkdir()
            (copy / "setup_updates.sh").write_text(self.script.read_text())
            git(copy, "init", "-q")
            git(copy, "remote", "add", "origin", "git@example:me/bob.git")
            done = subprocess.run(["bash", str(copy / "setup_updates.sh")], capture_output=True, text=True, timeout=20)
            self.assertEqual(done.returncode, 0)
            self.assertIn("already a git checkout", done.stdout)


if __name__ == "__main__":
    unittest.main()
