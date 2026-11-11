"""Update Bob from GitHub: `/update` shows what is new, `/update confirm` pulls it and restarts him.

Only works when ~/bob is a git checkout (setup_updates.sh does that). It pulls fast-forward only, checks that every
file still compiles, installs new requirements, and puts the old code back if anything looks wrong. Only the owner can
do it; Claude cannot.

[update] channel picks what "newest" means: "commit" (the default) follows the latest commit on main; "release" follows the
newest numbered release tag (26.11, 26.12, ...), so a half-finished commit is never installed. Either way it only moves forward.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

DEFAULT_BRANCH = "main"
RELEASE_TAG = re.compile(r"^v?\d+(\.\d+)*$")        # 26.11, 26.10.1, v1.0.0; not "26.12-beta" or "backup"
NOT_GIT = ("this copy of Bob isn't a git checkout, so he can't update himself. "
           "Run ./setup_updates.sh once (manual 02), or copy files with rsync as before")


def _run(args, cwd, timeout=120):
    try:
        done = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)
    return done.returncode, (done.stdout + done.stderr).strip()


class Updater:
    def __init__(self, root, run=_run, channel="commit"):
        self.root, self._run = Path(root), run
        self.channel = "release" if str(channel).lower() == "release" else "commit"

    def git(self, *args, timeout=120):
        return self._run(["git", *args], self.root, timeout)

    @property
    def is_git(self) -> bool:
        return (self.root / ".git").exists()

    def _branch(self):
        code, out = self.git("rev-parse", "--abbrev-ref", "HEAD")
        return out if code == 0 and out != "HEAD" else None

    def _ancestor(self, older: str, newer: str) -> bool:
        return self.git("merge-base", "--is-ancestor", older, newer)[0] == 0

    def _latest_release(self) -> str | None:
        """The newest numbered release tag we know about (after a fetch), or None."""
        code, out = self.git("tag", "--list", "--sort=-v:refname")
        tags = [t for t in out.splitlines() if RELEASE_TAG.match(t.strip())] if code == 0 else []
        return tags[0].strip() if tags else None

    def _fetch(self, branch: str):
        """Fetch from GitHub. In release mode also the tags, which is where releases live."""
        args = ["fetch", "--quiet"] + (["--tags", "--force"] if self.channel == "release" else []) + ["origin", branch]
        return self.git(*args)

    def _target(self, branch: str) -> tuple[str | None, str, str | None]:
        """(what to move to, what to call it, a problem). Call after _fetch."""
        if self.channel == "commit":
            return f"origin/{branch}", f"origin/{branch}", None
        tag = self._latest_release()
        if tag is None:
            return None, "", ("there is no numbered release on GitHub yet, so [update] channel = \"release\" has nothing to install. "
                              "Use channel = \"commit\" to follow main")
        return f"refs/tags/{tag}^{{commit}}", f"release {tag}", None

    def _detached_problem(self, branch: str) -> str | None:
        """A copy that isn't on a branch (left on a commit or tag by hand) can still be updated, as long as it is a plain
        earlier point of GitHub's main and no local work would be lost by moving onto it. Returns why not, or None."""
        remote = f"origin/{branch}"
        if not self._ancestor("HEAD", remote):
            return (f"this copy is on a commit that isn't part of GitHub's {branch} (it has its own changes), so I won't move it. "
                    f"If that is wrong, run: git checkout {branch}")
        if self.git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")[0] == 0 and not self._ancestor(branch, remote):
            return f"a local {branch} branch has changes GitHub doesn't, so I won't move it. Run: git status, then git log {branch}"
        return None

    def status(self) -> tuple[bool, str, int]:
        """(ok, text, commits_behind). Fetches from GitHub but changes nothing."""
        if not self.is_git:
            return False, NOT_GIT, 0
        branch = self._branch()
        detached = branch is None
        branch = branch or DEFAULT_BRANCH
        code, out = self._fetch(branch)
        if code != 0:
            return False, f"couldn't reach GitHub ({out.splitlines()[-1] if out else code}). Is the deploy key set up? (manual 02)", 0
        ref, label, problem = self._target(branch)
        if problem:
            return False, problem, 0
        code, count = self.git("rev-list", "--count", f"HEAD..{ref}")
        if code != 0 or not count.isdigit():
            return False, f"couldn't compare with {label}: {count}", 0
        behind = int(count)
        dirty = self.git("status", "--porcelain", "--untracked-files=no")[1]
        note = "\nNote: files here were changed by hand; /update confirm will refuse until they are committed or undone." if dirty else ""
        if detached:
            problem = self._detached_problem(branch)
            if problem:
                return False, problem, 0
            note += f"\nNote: this copy isn't on a branch (it was left on a commit); /update confirm will move it onto {branch}."
        if behind and not self._ancestor("HEAD", ref):
            return False, f"this copy has changes that {label} doesn't, so I won't move it (git status, then git log)", 0
        if behind == 0:
            return True, f"up to date with {label}.{note}", 0
        _, log = self.git("log", "--oneline", "-n", "10", f"HEAD..{ref}")
        more = f"\n  ... and {behind - 10} more" if behind > 10 else ""
        return True, f"{behind} new change{'s' * (behind != 1)} on GitHub ({label}):\n" + "\n".join("  " + line for line in log.splitlines()) + more + \
            f"\nType /update confirm to install them and restart Bob.{note}", behind

    def apply(self) -> tuple[bool, str, bool]:
        """(ok, text, changed). Pulls, checks, and rolls back on a problem."""
        if not self.is_git:
            return False, NOT_GIT, False
        if self.git("status", "--porcelain", "--untracked-files=no")[1]:
            return False, "files here were changed by hand, so I won't overwrite them. Commit or undo them first (git status)", False
        branch = self._branch()
        detached = branch is None
        branch = branch or DEFAULT_BRANCH
        before = self.git("rev-parse", "HEAD")[1]
        code, out = self._fetch(branch)
        if code != 0:
            return False, f"couldn't reach GitHub, nothing changed: {out.splitlines()[-1] if out else code}", False
        ref, label, problem = self._target(branch)
        if problem:
            return False, problem, False
        if detached:
            problem = self._detached_problem(branch)
            if problem:
                return False, problem, False
            if not self._ancestor("HEAD", ref):
                return False, f"this copy has changes that {label} doesn't, so I won't move it", False
            # Move onto the branch at the target. Only a fast-forward of what we already have: checked just above.
            code, out = self.git("checkout", "-q", "-B", branch, ref)
            if code == 0:
                self.git("branch", "-q", f"--set-upstream-to=origin/{branch}", branch)
        else:
            code, out = self.git("merge", "--ff-only", "--quiet", ref)
        if code != 0:
            return False, f"git couldn't move forward, nothing changed: {out.splitlines()[-1] if out else code}", False
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
        return True, f"updated {before[:7]} -> {after[:7]} ({label}):\n" + "\n".join("  " + l for l in summary.splitlines()[:10]), True

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
