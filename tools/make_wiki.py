#!/usr/bin/env python3
"""Builds the GitHub wiki from the manuals, so there is one place to edit them (manuals/) and the wiki never drifts.

    python3 tools/make_wiki.py [OUT_DIR]        (default: wiki-out)

GitHub wiki pages are flat files linked by page name without ".md", so this copies each manual under a readable name
("09-distance-sensor.md" becomes "09-Distance-sensor.md"), rewrites the links between manuals to match, points links
to other files in the repository (TRAINING_HEY_BOB.md, images, code) at GitHub, and writes Home, _Sidebar and _Footer.
Every link is resolved relative to the manuals/ folder; a link to something that does not exist stops the build, so a
dead link is found here and not by a reader. The .github/workflows/wiki.yml workflow runs this and pushes the result.

Links are rewritten in four forms: [text](target "title"), [text](<target>), reference definitions ([ref]: target) and
HTML href= / src=. Code (``` or ~~~ blocks, and `inline code`) is left exactly as written.
"""
from __future__ import annotations

import posixpath
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import quote, unquote

ROOT = Path(__file__).resolve().parent.parent
REPO_URL = "https://github.com/TECWiSaRd/Bob-Cena"
IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}

INLINE = re.compile(r'\]\((<[^>]*>|[^)\s]*)((?:\s+(?:"[^"]*"|\'[^\']*\'))?)\)')
REFDEF = re.compile(r"^(\s{0,3}\[[^\]]+\]:\s*)(<[^>]*>|\S+)")
HTMLREF = re.compile(r'(\b(?:href|src)\s*=\s*)(["\'])(.*?)\2', re.I)
CODESPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.S)      # may run across lines
FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
LISTITEM = re.compile(r"^\s{0,3}(?:[-*+]|\d+[.)])\s")
INDENTED = re.compile(r"^(?: {4}|\t)")


class LinkError(Exception):
    pass


class Site:
    def __init__(self, manuals: Path):
        self.manuals = manuals
        self.repo = manuals.parent
        self.files = sorted(manuals.glob("*.md"))
        self.names: dict[str, str] = {}
        seen: dict[str, str] = {}
        for p in self.files:
            name = "Home" if p.name.startswith("00-") else page_name(p)
            if name in seen:
                raise LinkError(f"{p.name} and {seen[name]} would both become the wiki page {name}")
            seen[name] = p.name
            self.names[p.name] = name

    def target(self, raw: str, source: str) -> str:
        """The wiki address for a link written in manual [source]."""
        t = raw[1:-1] if raw.startswith("<") and raw.endswith(">") else raw
        if not t or t.startswith("#") or re.match(r"^[a-z][a-z0-9+.-]*:", t, re.I) or t.startswith("//"):
            return raw                                     # same-page heading, web address, mailto:, ...
        path, hash_, anchor = t.partition("#")
        path = unquote(path)
        resolved = posixpath.normpath(posixpath.join("manuals", path))
        if resolved.startswith("../") or resolved == "..":
            raise LinkError(f"{source}: '{raw}' points outside the repository")
        if resolved.startswith("manuals/") and "/" not in resolved[len("manuals/"):] and posixpath.basename(resolved) in self.names:
            return self.names[posixpath.basename(resolved)] + hash_ + anchor
        found = self.repo / resolved
        if not found.exists():
            raise LinkError(f"{source}: '{raw}' points at {resolved}, which does not exist")
        kind = "tree" if found.is_dir() else "blob"
        suffix = "?raw=true" if kind == "blob" and Path(resolved).suffix.lower() in IMAGES else ""
        return f"{REPO_URL}/{kind}/main/{quote(resolved)}{suffix}{hash_}{anchor}"

    def rewrite(self, text: str, source: str = "?") -> str:
        """Rewrite the links in prose. Code is left as written: fenced blocks (any length of ``` or ~~~, closed by a
        fence at least as long), indented blocks (4 spaces or a tab, unless they continue a list), and `code spans`,
        which may run across lines."""
        out: list[str] = []
        block: list[str] = []
        fence = None                          # (character, length) while inside a fenced block
        prev_blank, in_list, in_indented = True, False, False

        def flush():
            if block:
                out.extend(self._prose("\n".join(block), source).split("\n"))
                block.clear()

        for line in text.split("\n"):
            if fence:
                out.append(line)
                m = FENCE.match(line)
                if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= fence[1] and line.strip().strip(fence[0]) == "":
                    fence = None
                continue
            m = FENCE.match(line)
            if m:
                flush()
                out.append(line)
                fence, prev_blank, in_indented = (m.group(1)[0], len(m.group(1))), False, False
                continue
            if not line.strip():
                flush()
                out.append(line)
                prev_blank = True
                continue
            if INDENTED.match(line) and (in_indented or (prev_blank and not in_list)):
                flush()
                out.append(line)
                in_indented, prev_blank = True, False
                continue
            if not INDENTED.match(line):
                in_indented = False
                if LISTITEM.match(line):
                    in_list = True
                elif prev_blank:
                    in_list = False
            if REFDEF.match(line):
                flush()
                out.append(REFDEF.sub(lambda m: m.group(1) + self.target(m.group(2), source), line))
            else:
                block.append(line)
            prev_blank = False
        flush()
        return "\n".join(out)

    def _prose(self, text: str, source: str) -> str:
        # Work on the stretches between code spans, so `[x](foo.md)` shown as an example stays as written.
        parts, last = [], 0
        for m in CODESPAN.finditer(text):
            parts.append(self._links(text[last:m.start()], source))
            parts.append(m.group(0))
            last = m.end()
        parts.append(self._links(text[last:], source))
        return "".join(parts)

    def _links(self, s: str, source: str) -> str:
        s = INLINE.sub(lambda m: "](" + self.target(m.group(1), source) + m.group(2) + ")", s)
        return HTMLREF.sub(lambda m: m.group(1) + m.group(2) + self.target(m.group(3), source) + m.group(2), s)


def page_name(path: Path) -> str:
    """'09-distance-sensor.md' -> '09-Distance-sensor' (number kept so the sidebar sorts in manual order)."""
    num, _, rest = path.stem.partition("-")
    rest = re.sub(r"[^A-Za-z0-9]+", "-", rest).strip("-")
    return f"{num}-{rest[:1].upper() + rest[1:]}"


def title_of(text: str, stem: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return re.sub(r"^Manual \d+:\s*", "", line[2:].strip())
    return stem.partition("-")[2].replace("-", " ").capitalize() or stem


def escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


HOME_OLD, HOME_NEW = "This folder has one manual", "This wiki has one page"


def build(manuals: Path = ROOT / "manuals", out: Path = ROOT / "wiki-out") -> list[str]:
    site = Site(manuals)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    sidebar = ["**[Home](Home)**", ""]
    for p in site.files:
        text = p.read_text(encoding="utf-8")
        name = site.names[p.name]
        body = site.rewrite(text, p.name)
        if name == "Home":
            if HOME_OLD not in body:
                raise LinkError(f"{p.name} no longer says '{HOME_OLD}', so the wiki Home would still call itself a folder: update HOME_OLD in make_wiki.py")
            body = body.replace(HOME_OLD, HOME_NEW)
        (out / f"{name}.md").write_text(body.rstrip() + "\n", encoding="utf-8")
        if name != "Home":
            sidebar.append(f"- [{p.stem.split('-')[0]} {escape(title_of(text, p.stem))}]({name})")
    sidebar += ["", f"[Source on GitHub]({REPO_URL})"]
    (out / "_Sidebar.md").write_text("\n".join(sidebar) + "\n", encoding="utf-8")
    (out / "_Footer.md").write_text(
        f"These pages are generated from the `manuals/` folder in [the repository]({REPO_URL}). "
        "To change one, edit it there; edits made here will be overwritten.\n", encoding="utf-8")
    return sorted(p.name for p in out.glob("*.md"))


if __name__ == "__main__":
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "wiki-out"
    try:
        made = build(out=dest)
    except LinkError as e:
        sys.exit(f"wiki build stopped: {e}")
    print(f"wrote {len(made)} files to {dest}")
