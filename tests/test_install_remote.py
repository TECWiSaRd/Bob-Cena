"""Checks for install_remote.sh with pretend system commands (it never touches this computer's real users or groups)."""
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STUBS = {
    "sudo": 'exec "$@"',
    "getent": '[ -f "$STATE/group_$2" ]',
    "groupadd": 'touch "$STATE/group_$1"; echo "groupadd $*" >> "$STATE/calls"',
    "usermod": 'echo "usermod $*" >> "$STATE/calls"; for g; do :; done; echo "$g" >> "$STATE/member_$USERARG"',
    "gpasswd": 'echo "gpasswd $*" >> "$STATE/calls"',
    "id": '''case "$1" in
  -u) echo 1000;;
  -nG) cat "$STATE/groups_$2" 2>/dev/null || echo "$2";;
  *) [ -f "$STATE/user_$1" ];;
esac''',
}


class InstallRemote(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name)
        self.state, self.opt, self.bin, self.stubs = t / "state", t / "opt", t / "bin", t / "stubs"
        for d in (self.state, self.bin, self.stubs):
            d.mkdir()
        for name, body in STUBS.items():
            p = self.stubs / name
            p.write_text("#!/bin/sh\n" + body + "\n")
            p.chmod(0o755)
        for user in ("kai", "alex", "adam"):
            (self.state / f"user_{user}").write_text("")
        self.env = {**os.environ, "PATH": f"{self.stubs}:{os.environ['PATH']}", "STATE": str(self.state),
                    "BOB_OPT_DIR": str(self.opt), "BOB_BIN_DIR": str(self.bin), "BOB_OWNER": "adam"}

    def run_script(self, *args, answer=None, env=None):
        # `id -u` must not be root even if the tests run as root, so the stub answers 1000
        return subprocess.run(["bash", str(ROOT / "install_remote.sh"), *args], input=answer, text=True,
                              capture_output=True, env={**self.env, **(env or {})}, cwd=ROOT)

    def calls(self):
        f = self.state / "calls"
        return f.read_text().splitlines() if f.exists() else []

    def test_setup_creates_groups_copies_the_viewer_and_writes_the_command(self):
        r = self.run_script("--yes")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), ["groupadd bobops", "groupadd bobview"])
        self.assertTrue((self.opt / "remote.py").exists() and (self.opt / "console.py").exists())
        cmd = self.bin / "bob-console"
        self.assertTrue(cmd.stat().st_mode & stat.S_IXUSR)
        text = cmd.read_text()
        self.assertIn(f'exec python3 "{self.opt}/remote.py" --owner "adam"', text)
        self.assertIn("--socket \"/tmp/bob-console.sock\"", text)
        self.assertIn('"$@"', text)                                  # extra arguments are passed through
        self.assertIn("enabled = true", r.stdout)                  # and it says what to do next

    def test_running_it_again_does_not_recreate_groups(self):
        self.run_script("--yes")
        (self.state / "calls").unlink()
        (self.state / "group_bobops").write_text("")
        (self.state / "group_bobview").write_text("")
        self.assertEqual(self.run_script("--yes").returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_it_asks_first_and_cancels_on_anything_but_yes(self):
        r = self.run_script(answer="n\n")
        self.assertIn("Cancelled", r.stdout)
        self.assertFalse(self.opt.exists())
        self.assertIn("creates two groups", r.stdout)               # it told them what it would change

    def test_add_operator_and_viewer(self):
        (self.state / "group_bobops").write_text("")
        (self.state / "group_bobview").write_text("")
        r = self.run_script("--add", "kai", env={"USERARG": "kai"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("usermod -aG bobops kai", self.calls())
        self.assertIn("commands allowed", r.stdout)
        r = self.run_script("--add", "alex", "--view", env={"USERARG": "alex"})
        self.assertIn("usermod -aG bobview alex", self.calls())
        self.assertIn("watch only", r.stdout)

    def test_add_refuses_unknown_users_the_owner_and_missing_groups(self):
        (self.state / "group_bobops").write_text("")
        self.assertNotEqual(self.run_script("--add", "nobody").returncode, 0)
        self.assertIn("no Pi user", self.run_script("--add", "nobody").stdout)
        self.assertIn("is you", self.run_script("--add", "adam").stdout)
        self.assertIn("Give the Pi user's name", self.run_script("--add").stdout)
        (self.state / "group_bobops").unlink()
        self.assertIn("Run", self.run_script("--add", "kai").stdout)
        self.assertEqual(self.calls(), [])

    def test_a_user_with_sudo_gets_a_warning(self):
        (self.state / "group_bobops").write_text("")
        (self.state / "groups_kai").write_text("kai sudo adm\n")
        r = self.run_script("--add", "kai", env={"USERARG": "kai"})
        self.assertIn("'sudo' group", r.stdout)
        self.assertIn("gpasswd -d kai sudo", r.stdout)

    def test_remove_only_touches_groups_they_are_in(self):
        (self.state / "groups_kai").write_text("kai bobview\n")
        r = self.run_script("--remove", "kai")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), ["gpasswd -d kai bobview"])

    def test_undo_removes_the_command_and_the_copy(self):
        self.run_script("--yes")
        self.assertEqual(self.run_script("--undo").returncode, 0)
        self.assertFalse((self.bin / "bob-console").exists())
        self.assertFalse(self.opt.exists())


if __name__ == "__main__":
    unittest.main()
