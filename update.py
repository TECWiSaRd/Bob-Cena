"""Update Bob from GitHub: `/update` shows what is new, `/update confirm` pulls it and restarts him.

Only works when ~/bob is a git checkout (setup_updates.sh does that). It pulls fast-forward only, checks that every
file still compiles, installs new requirements, and puts the old code back if anything looks wrong. Only the owner can
do it; Claude cannot.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

NOT_GIT = ("this copy of Bob isn't a git checkout, so he can't update himself. "
           "Run ./setup_updates.sh once (manual 02), or copy files with rsync as before")


def _run(args, cwd, timeout=120):
    try:
        done = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)
    return done.returncode, (done.stdout + done.stderr).strip()


class Updater:
    def __init__(self, root, run=_run):
        self.root, self._run = Path(root), run

    def git(self, *args, timeout=120):
        return self._run(["git", *args], self.root, timeout)

    @property
    def is_git(self) -> bool:
        return (self.root / ".git").exists()

    def _branch(self):
        code, out = self.git("rev-parse", "--abbrev-ref", "HEAD")
        return out if code == 0 and out != "HEAD" else None

    def status(self) -> tuple[bool, str, int]:
        """(ok, text, commits_behind). Fetches from GitHub but changes nothing."""
        if not self.is_git:
            return False, NOT_GIT, 0
        branch = self._branch()
        if not branch:
            return False, "git isn't on a branch (detached HEAD), so /update can't tell what is new", 0
        code, out = self.git("fetch", "--quiet", "origin", branch)
        if code != 0:
            return False, f"couldn't reach GitHub ({out.splitlines()[-1] if out else code}). Is the deploy key set up? (manual 02)", 0
        code, count = self.git("rev-list", "--count", f"HEAD..origin/{branch}")
        if code != 0 or not count.isdigit():
            return False, f"couldn't compare with origin/{branch}: {count}", 0
        behind = int(count)
        dirty = self.git("status", "--porcelain", "--untracked-files=no")[1]
        note = "\nNote: files here were changed by hand; /update confirm will refuse until they are committed or undone." if dirty else ""
        if behind == 0:
            return True, f"up to date with origin/{branch}.{note}", 0
        _, log = self.git("log", "--oneline", "-n", "10", f"HEAD..origin/{branch}")
        more = f"\n  ... and {behind - 10} more" if behind > 10 else ""
        return True, f"{behind} new change{'s' * (behind != 1)} on GitHub:\n" + "\n".join("  " + line for line in log.splitlines()) + more + \
            f"\nType /update confirm to install them and restart Bob.{note}", behind

    def apply(self) -> tuple[bool, str, bool]:
        """(ok, text, changed). Pulls, checks, and rolls back on a problem."""
        if not self.is_git:
            return False, NOT_GIT, False
        if self.git("status", "--porcelain", "--untracked-files=no")[1]:
            return False, "files here were changed by hand, so I won't overwrite them. Commit or undo them first (git status)", False
        branch = self._branch()
        if not branch:
            return False, "git isn't on a branch", False
        before = self.git("rev-parse", "HEAD")[1]
        code, out = self.git("pull", "--ff-only", "--quiet", "origin", branch)
        if code != 0:
            return False, f"git pull failed, nothing changed: {out.splitlines()[-1] if out else code}", False
        after = self.git("rev-parse", "HEAD")[1]
        if after == before:
            return True, "already up to date", False
        problems = self._check_files()
        if not problems and self.git("diff", "--name-only", before, after, "--", "requirements.txt")[1]:
            code, out = self._run([sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"], self.root, 600)
            if code != 0:
                problems = [f"installing the new requirements failed: {out.splitlines()[-1] if out else code}"]
        if problems:
            self.git("reset", "--hard", before)
            return False, "the new code didn't pass its checks, so I put the old code back: " + "; ".join(problems[:3]), False
        _, summary = self.git("log", "--oneline", f"{before}..{after}")
        return True, f"updated {before[:7]} -> {after[:7]}:\n" + "\n".join("  " + l for l in summary.splitlines()[:10]), True

    def _check_files(self) -> list[str]:
        bad = []
        for path in sorted(self.root.glob("*.py")):
            try:
                compile(path.read_text(), path.name, "exec")        # a syntax check only; nothing is written
            except SyntaxError as e:
                bad.append(f"{path.name} line {e.lineno}: {e.msg}")
            except (OSError, UnicodeDecodeError, ValueError):
                bad.append(f"{path.name} can't be read")
        return bad
