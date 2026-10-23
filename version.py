"""What version of the code is this? A version name, plus a short fingerprint of the files, so a Pi that holds a mix of
old and new files (a copy that stopped half way, a friend's stale bob-console) can be spotted at a glance."""
from __future__ import annotations

import hashlib
import subprocess
from datetime import datetime
from pathlib import Path

__version__ = "26.11-dev"


def files_hash(paths) -> str:
    """An 8-character fingerprint of the named files' contents (and names)."""
    digest = hashlib.sha256()
    for path in sorted(Path(p) for p in paths):
        try:
            digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
        except OSError:
            digest.update(path.name.encode() + b"\0missing\0")
    return digest.hexdigest()[:8]


def code_hash(root) -> str:
    return files_hash(Path(root).glob("*.py"))


def console_hash(root) -> str:
    """The two files a friend's bob-console copy consists of."""
    root = Path(root)
    return files_hash([root / "console.py", root / "remote.py"])


def _git(root, *args) -> str | None:
    try:
        done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def describe(root) -> str:
    root = Path(root)
    newest = max((p.stat().st_mtime for p in root.glob("*.py")), default=0)
    parts = [f"Bob {__version__}", f"code {code_hash(root)}"]
    if newest:
        parts.append(f"newest file {datetime.fromtimestamp(newest):%Y-%m-%d %H:%M}")
    commit = _git(root, "rev-parse", "--short", "HEAD") if (root / ".git").exists() else None
    if commit:
        dirty = _git(root, "status", "--porcelain", "--untracked-files=no")
        parts.append(f"git {commit}{' (changed locally)' if dirty else ''}")
    else:
        parts.append("copied with rsync (not a git checkout: see manual 02 to enable /update)")
    return ", ".join(parts)
