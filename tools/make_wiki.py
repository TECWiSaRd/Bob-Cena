#!/usr/bin/env python3
"""Builds the GitHub wiki from the manuals, so there is one place to edit them (manuals/) and the wiki never drifts.

    python3 tools/make_wiki.py [OUT_DIR]        (default: wiki-out)

GitHub wiki pages are flat files linked by page name without ".md", so this copies each manual under a readable name
("09-distance-sensor.md" becomes "09-Distance-sensor.md"), rewrites the links between manuals to match, points links
to files that are not manuals (TRAINING_HEY_BOB.md, JOHN_PROMPT.md) at the repository, and writes Home, _Sidebar and
_Footer. The .github/workflows/wiki.yml workflow runs this and pushes the result to the wiki.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO_URL = "https://github.com/TECWiSaRd/Bob-Cena"
LINK = re.compile(r"\]\(([^)\s]+)\)")


def page_name(path: Path) -> str:
    """'09-distance-sensor.md' -> '09-Distance-sensor' (number kept so the sidebar sorts in manual order)."""
    stem = path.stem
    num, _, rest = stem.partition("-")
    rest = rest.replace("-", " ").strip()
    rest = rest[:1].upper() + rest[1:]
    return f"{num}-{rest.replace(' ', '-')}"


def title_of(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return re.sub(r"^Manual \d+:\s*", "", line[2:].strip())
    return fallback


def rewrite_links(text: str, names: dict[str, str]) -> str:
    """Point manual-to-manual links at wiki page names and other repository files at GitHub. Code blocks are left alone."""
    out, fenced = [], False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced:
            line = LINK.sub(lambda m: "](" + _target(m.group(1), names) + ")", line)
        out.append(line)
    return "\n".join(out)


def _target(target: str, names: dict[str, str]) -> str:
    if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("#"):
        return target                                      # a web address, a mailto:, or a heading on the same page
    path, hash_, anchor = target.partition("#")
    base = Path(path).name
    if base in names:
        return names[base] + (hash_ + anchor)
    if path.startswith("../") or path.startswith("manuals/") or "/" not in path:
        return f"{REPO_URL}/blob/main/{path.removeprefix('../')}" + (hash_ + anchor)
    return target


def build(manuals: Path = ROOT / "manuals", out: Path = ROOT / "wiki-out") -> list[str]:
    files = sorted(p for p in manuals.glob("*.md"))
    names = {p.name: ("Home" if p.name.startswith("00-") else page_name(p)) for p in files}
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    sidebar = ["**[Home](Home)**", ""]
    for p in files:
        text = p.read_text(encoding="utf-8")
        name = names[p.name]
        body = rewrite_links(text, names)
        if name == "Home":
            body = body.replace("This folder has one manual", "This wiki has one page")
        (out / f"{name}.md").write_text(body.rstrip() + "\n", encoding="utf-8")
        if name != "Home":
            sidebar.append(f"- [{p.stem.split('-')[0]} {title_of(text, p.stem)}]({name})")
    sidebar += ["", f"[Source on GitHub]({REPO_URL})"]
    (out / "_Sidebar.md").write_text("\n".join(sidebar) + "\n", encoding="utf-8")
    (out / "_Footer.md").write_text(
        f"These pages are generated from the `manuals/` folder in [the repository]({REPO_URL}). "
        "To change one, edit it there; edits made here will be overwritten.\n", encoding="utf-8")
    return sorted(p.name for p in out.glob("*.md"))


if __name__ == "__main__":
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "wiki-out"
    made = build(out=dest)
    print(f"wrote {len(made)} files to {dest}")
