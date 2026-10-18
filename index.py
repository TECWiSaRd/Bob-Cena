"""A searchable index of Bob's records: one SQLite file with full-text search.

The files stay the truth (timeline *.jsonl, memory.json, people.json, radio.jsonl, bob.log, the manuals). This
database, logs/index.db, is only a fast way to search them. It is disposable: if it is ever damaged, Bob deletes
it and builds it again.

Reading is incremental: for each growing file the index remembers how far it has read, so the cost of keeping
up does not grow with the size of the history. Rows follow the files' retention: when the timeline deletes a
day's file, that day's rows go too, and /timeline clear removes them straight away.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("bob.index")

SCHEMA_VERSION = 1
# What Claude may recall. Notes and people are already in every status report, and the log and manuals are for
# the operator, so the model only gets the history of what happened.
AI_SOURCES = ("timeline", "radio")

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs(
    id INTEGER PRIMARY KEY, source TEXT NOT NULL, kind TEXT NOT NULL, ts REAL NOT NULL,
    ref TEXT, picture TEXT, body TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS docs_ts ON docs(ts);
CREATE INDEX IF NOT EXISTS docs_ref ON docs(source, ref);
CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
    body, kind, content='docs', content_rowid='id', tokenize='porter unicode61');
CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON docs BEGIN
    INSERT INTO docs_fts(rowid, body, kind) VALUES (new.id, new.body, new.kind);
END;
CREATE TRIGGER IF NOT EXISTS docs_ad AFTER DELETE ON docs BEGIN
    INSERT INTO docs_fts(docs_fts, rowid, body, kind) VALUES ('delete', old.id, old.body, old.kind);
END;
CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, source TEXT NOT NULL, pos INTEGER NOT NULL, stamp REAL NOT NULL);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
"""

LOG_LINE = re.compile(r"^\d\d:\d\d:\d\d (WARNING|ERROR)\s+(.*)")


def parse_since(word: str, now: float) -> float | None:
    """'2h', '30m', '3d', 'today', 'yesterday' or '2026-10-16' -> a time, or None if it isn't understood."""
    word = word.lower()
    start_of_day = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
    if word == "today":
        return start_of_day.timestamp()
    if word == "yesterday":
        return (start_of_day - timedelta(days=1)).timestamp()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([mhd])", word)
    if m:
        return now - float(m.group(1)) * {"m": 60, "h": 3600, "d": 86400}[m.group(2)]
    try:
        return datetime.strptime(word, "%Y-%m-%d").timestamp()
    except ValueError:
        return None


def parse_query(raw: str, now: float) -> tuple[str, dict]:
    """Split 'lens covered kind:estop since:2d' into the words to search for and the filters."""
    words, filters = [], {}
    for tok in raw.split():
        key, _, val = tok.partition(":")
        if val and key.lower() in ("kind", "source", "since"):
            if key.lower() == "since":
                ts = parse_since(val, now)
                if ts is None:
                    raise ValueError(f"I don't understand since:{val} (try 2h, 3d, today, yesterday or 2026-10-16)")
                filters["since"] = ts
            else:
                filters[key.lower()] = val.lower()
        else:
            words.append(tok)
    return " ".join(words), filters


def fts_expression(text: str) -> str:
    """Words to a safe full-text query: every word must match, as a prefix."""
    return " ".join(f'"{w}"*' for w in re.findall(r"[\w']+", text.lower()) if w.strip("'"))


class Index:
    def __init__(self, cfg, base: Path, clock=time.time):
        self.cfg, self.base, self._clock = cfg, base, clock
        self.enabled = cfg.enabled
        self.path = base / "logs" / "index.db"
        self.timeline_dir = base / "logs" / "timeline"
        self._lock = threading.Lock()
        self._halt = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_sync = 0.0
        self.last_error = ""
        self.timeout = 5.0          # seconds to wait for another writer before giving up until the next sync

    # ---- running ----------------------------------------------------------------------------------------
    def start(self) -> None:
        if not self.enabled or self._thread:
            return
        self._halt.clear()
        self._thread = threading.Thread(target=self._loop, name="index", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._halt.set()
        if self._thread:
            self._thread.join(3)
            self._thread = None

    def _loop(self) -> None:
        while not self._halt.is_set():
            self.sync()
            self._halt.wait(self.cfg.interval_s)

    # ---- database -----------------------------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=self.timeout)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        db.executescript(SCHEMA)
        row = db.execute("SELECT v FROM meta WHERE k='version'").fetchone()
        if row is None:
            db.execute("INSERT INTO meta VALUES('version', ?)", (str(SCHEMA_VERSION),))
            db.commit()
        elif row[0] != str(SCHEMA_VERSION):
            db.close()
            raise sqlite3.DatabaseError("index format changed")
        return db

    def _reset(self) -> None:
        """Throw the whole database away: it is only a copy, and the next sync builds it again."""
        for suffix in ("", "-wal", "-shm"):
            Path(str(self.path) + suffix).unlink(missing_ok=True)

    def sync(self) -> None:
        """Read whatever is new in the source files. Safe to call from anywhere, any time."""
        if not self.enabled:
            return
        with self._lock:
            try:
                db = self._connect()
            except sqlite3.DatabaseError as e:
                if not any(w in str(e).lower() for w in ("malformed", "not a database", "corrupt", "format changed", "disk image")):
                    self.last_error = str(e)      # for example "database is locked": try again next time, never wipe it
                    return
                log.warning("search index damaged (%s): rebuilding it", e)
                self._reset()
                try:
                    db = self._connect()
                except (sqlite3.Error, OSError) as e2:
                    self.last_error = str(e2)
                    return
            except OSError as e:
                self.last_error = str(e)
                return
            try:
                with db:
                    self._read_all(db)
                self.last_sync, self.last_error = self._clock(), ""
            except (sqlite3.Error, OSError) as e:
                self.last_error = str(e)
                log.warning("search index update failed (%s)", e)
            finally:
                db.close()

    def _read_all(self, db: sqlite3.Connection) -> None:
        now = self._clock()
        for path in sorted(self.timeline_dir.glob("*.jsonl")):
            self._tail(db, path, "timeline", self._timeline_row)
        self._drop_missing(db, "timeline")
        self._tail(db, self.base / "logs" / "radio.jsonl", "radio", self._radio_row)
        if self.cfg.log_warnings:
            self._tail(db, self.base / "logs" / "bob.log", "log", self._log_row)
        self._mirror(db, self.base / "memory.json", "note", self._note_docs)
        self._mirror(db, self.base / "people.json", "person", self._person_docs)
        if self.cfg.manuals:
            for path in sorted((self.base / "manuals").glob("*.md")):
                self._mirror(db, path, "manual", self._manual_docs)
            self._mirror(db, self.base / "README.md", "manual", self._manual_docs)
        self._age(db, now)

    # ---- reading the sources -------------------------------------------------------------------------------
    def _tail(self, db, path: Path, source: str, make) -> None:
        """Index the lines added since last time. A shrunken file (rotated or replaced) is read again from the top."""
        key = str(path)
        try:
            size = path.stat().st_size
        except OSError:
            return
        row = db.execute("SELECT pos FROM files WHERE path=?", (key,)).fetchone()
        pos = row[0] if row else 0
        if size < pos:
            if source != "log":
                db.execute("DELETE FROM docs WHERE source=? AND ref=?", (source, path.name))
            pos = 0
        if size == pos:
            return
        with open(path, "rb") as f:
            f.seek(pos)
            chunk = f.read(size - pos)
        end = chunk.rfind(b"\n") + 1              # only whole lines: a half-written one is picked up next time
        for raw in chunk[:end].splitlines():
            doc = make(raw.decode("utf-8", "replace"), path)
            if doc:
                self._add(db, source, path.name, *doc)
        db.execute("INSERT OR REPLACE INTO files VALUES(?,?,?,?)", (key, source, pos + end, self._clock()))

    @staticmethod
    def _add(db, source: str, ref: str, kind: str, ts: float, body: str, picture: str | None = None) -> None:
        db.execute("INSERT INTO docs(source, kind, ts, ref, picture, body) VALUES (?,?,?,?,?,?)",
                   (source, kind, ts, ref, picture, body[:2000]))

    @staticmethod
    def _timeline_row(line: str, path: Path):
        try:
            row = json.loads(line)
            ts = datetime.fromisoformat(row["t"]).timestamp()
        except (ValueError, KeyError, TypeError):
            return None
        body = " ".join(f"{k}={v}" for k, v in row.items() if k not in ("t", "kind", "picture"))
        return str(row.get("kind", "?")), ts, body, row.get("picture")

    @staticmethod
    def _radio_row(line: str, path: Path):
        try:
            row = json.loads(line)
            return "message", float(row["ts"]), f"{row.get('from', '?')} -> {row.get('to', '?')}: {row.get('text', '')}"
        except (ValueError, KeyError, TypeError):
            return None

    def _log_row(self, line: str, path: Path):
        m = LOG_LINE.match(line)
        return (m.group(1).lower(), self._clock(), m.group(2)) if m else None

    def _mirror(self, db, path: Path, source: str, make) -> None:
        """Keep a small file's rows in step with the file: when it changes, replace its rows."""
        key = str(path)
        try:
            st = path.stat()
        except OSError:
            if db.execute("SELECT 1 FROM files WHERE path=?", (key,)).fetchone():
                db.execute("DELETE FROM docs WHERE source=? AND ref=?", (source, path.name))
                db.execute("DELETE FROM files WHERE path=?", (key,))
            return
        stamp = st.st_mtime + st.st_size / 1e9
        row = db.execute("SELECT stamp FROM files WHERE path=?", (key,)).fetchone()
        if row and abs(row[0] - stamp) < 1e-9:
            return
        db.execute("DELETE FROM docs WHERE source=? AND ref=?", (source, path.name))
        try:
            docs = make(path)
        except (OSError, ValueError):
            docs = []        # a damaged file: index nothing from it for now
        for kind, body in docs:
            self._add(db, source, path.name, kind, st.st_mtime, body)
        db.execute("INSERT OR REPLACE INTO files VALUES(?,?,?,?)", (key, source, st.st_size, stamp))

    @staticmethod
    def _note_docs(path: Path):
        data = json.loads(path.read_text())
        return [("note", str(n)) for n in data] if isinstance(data, list) else []

    @staticmethod
    def _person_docs(path: Path):
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return []
        return [("person", f"{name}: {e.get('description', '')} {e.get('notes', '')} (last seen {e.get('seen', '?')})")
                for name, e in data.items() if isinstance(e, dict)]

    @staticmethod
    def _manual_docs(path: Path):
        """One row per section of a manual, long sections cut into pieces so a hit points at the right place."""
        docs, title, buf = [], path.stem, []

        def flush():
            text = " ".join(" ".join(buf).split())
            for i in range(0, len(text), 900):
                docs.append(("manual", f"{path.name} | {title} | {text[i:i + 900]}"))

        for line in path.read_text().splitlines():
            if line.startswith("#"):
                flush()
                title, buf = line.lstrip("# ").strip() or title, []
            else:
                buf.append(line)
        flush()
        return docs

    # ---- keeping it tidy -------------------------------------------------------------------------------------
    def _drop_missing(self, db, source: str) -> None:
        """Rows from files that have been deleted (old days, /timeline clear, the size cap) go too."""
        for key, in db.execute("SELECT path FROM files WHERE source=?", (source,)).fetchall():
            if not Path(key).exists():
                db.execute("DELETE FROM docs WHERE source=? AND ref=?", (source, Path(key).name))
                db.execute("DELETE FROM files WHERE path=?", (key,))

    def _age(self, db, now: float) -> None:
        cutoff = now - self.cfg.keep_days * 86400
        db.execute("DELETE FROM docs WHERE source IN ('log','radio') AND ts < ?", (cutoff,))
        (n,) = db.execute("SELECT COUNT(*) FROM docs").fetchone()
        if n > self.cfg.max_rows:   # a safety net: drop the oldest history, never the manuals, notes or people
            db.execute("DELETE FROM docs WHERE id IN (SELECT id FROM docs WHERE source IN ('timeline','radio','log') "
                       "ORDER BY ts LIMIT ?)", (n - self.cfg.max_rows,))

    def forget(self, source: str) -> None:
        """Remove one source's rows now (for example after /timeline clear), and re-read it from scratch next time."""
        if not self.enabled:
            return
        with self._lock:
            try:
                db = self._connect()
                with db:
                    db.execute("DELETE FROM docs WHERE source=?", (source,))
                    db.execute("DELETE FROM files WHERE source=?", (source,))
                db.close()
            except (sqlite3.Error, OSError) as e:
                self.last_error = str(e)

    def rebuild(self) -> str:
        with self._lock:
            self._reset()
        self.sync()
        return "search index rebuilt" if not self.last_error else f"rebuild failed: {self.last_error}"

    # ---- searching -------------------------------------------------------------------------------------------
    def search(self, raw: str, limit: int = 20, sources: tuple[str, ...] | None = None, since_default: float | None = None):
        """Rows matching 'words kind:x source:y since:2d', newest first. Raises ValueError for a bad query."""
        if not self.enabled:
            return []
        text, f = parse_query(raw, self._clock())
        self.sync()
        where, args, join = [], [], ""
        expr = fts_expression(text)
        if expr:
            join = "JOIN docs_fts ON docs_fts.rowid = d.id"
            where.append("docs_fts MATCH ?")
            args.append(expr)
        if "kind" in f:
            where.append("d.kind = ?")
            args.append(f["kind"])
        if "source" in f:
            where.append("d.source = ?")
            args.append(f["source"])
        if sources:
            where.append(f"d.source IN ({','.join('?' * len(sources))})")
            args += list(sources)
        since = f.get("since", since_default)
        if since is not None:
            where.append("d.ts >= ?")
            args.append(since)
        sql = (f"SELECT d.source, d.kind, d.ts, d.picture, d.body FROM docs d {join} "
               f"{'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY d.ts DESC LIMIT ?")
        with self._lock:
            try:
                db = self._connect()
                try:
                    rows = db.execute(sql, args + [limit]).fetchall()
                finally:
                    db.close()
            except sqlite3.Error as e:
                raise ValueError(f"search failed ({e})")
        return [{"source": s, "kind": k, "ts": t, "picture": p, "body": b} for s, k, t, p, b in rows]

    def format_hit(self, hit: dict, width: int = 160) -> str:
        when = datetime.fromtimestamp(hit["ts"]).strftime("%b %d %H:%M:%S")
        pic = ""
        if hit["picture"]:
            pic = f"  [picture {hit['picture']}]" if (self.timeline_dir / "thumbs" / hit["picture"]).exists() \
                else "  [picture deleted]"
        body = hit["body"] if len(hit["body"]) <= width else hit["body"][:width - 1] + "…"
        return f"{when}  {hit['source']}/{hit['kind']}  {body}{pic}"

    def recall(self, query: str, days: float | None = None, limit: int = 5) -> list[str]:
        """What Claude gets: a few short lines of history, never the operator-only sources."""
        since = self._clock() - days * 86400 if days else None
        try:
            hits = self.search(query, limit, AI_SOURCES, since)
        except ValueError:
            return []
        return [self.format_hit(h, 140) for h in hits]

    def status(self) -> str:
        if not self.enabled:
            return "search index off ([index] enabled = true)"
        try:
            db = self._connect()
            try:
                counts = dict(db.execute("SELECT source, COUNT(*) FROM docs GROUP BY source").fetchall())
            finally:
                db.close()
        except (sqlite3.Error, OSError) as e:
            return f"search index unavailable ({e})"
        size = sum(p.stat().st_size for p in self.path.parent.glob("index.db*")) / 1e6
        parts = ", ".join(f"{n} {s}" for s, n in sorted(counts.items())) or "empty so far"
        age = f"updated {self._clock() - self.last_sync:.0f}s ago" if self.last_sync else "not updated yet"
        return f"search index: {parts} ({size:.1f} MB, {age})" + (f"; last problem: {self.last_error}" if self.last_error else "")
