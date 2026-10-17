"""Event timeline: a local record of what Bob saw, decided and did, for tuning and for reviewing incidents.

Off by default. When on, it appends one JSON line per event to logs/timeline/YYYY-MM-DD.jsonl and saves small
camera thumbnails (at most one every `thumb_every_s`) in logs/timeline/thumbs/. Old files are deleted after
`keep_days`, and the folder is kept under `max_mb`. Everything stays on the Pi.

Thumbnails can show people. Leave `thumbnails = false`, or run /timeline clear, when that matters.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger("bob.timeline")


def _short(value, n: int = 200):
    return value[:n] if isinstance(value, str) else value


class Timeline:
    def __init__(self, cfg, directory: Path, clock=time.time):
        self.cfg = cfg
        self.dir = directory
        self.enabled = cfg.enabled
        self._clock = clock
        self._lock = threading.Lock()
        self._last_thumb = 0.0
        self._last_prune = 0.0
        self.count = 0     # events written since Bob started
        if self.enabled:
            self._prune(force=True)

    # ---- writing --------------------------------------------------------------------------------------
    def record(self, kind: str, **data) -> None:
        """Append one event. Never raises: a full disk must not stop Bob."""
        if not self.enabled:
            return
        now = self._clock()
        row = {"t": datetime.fromtimestamp(now).isoformat(timespec="milliseconds"), "kind": kind}
        row.update({k: _short(v) for k, v in data.items() if v is not None})
        try:
            with self._lock:
                self.dir.mkdir(parents=True, exist_ok=True)
                path = self.dir / f"{datetime.fromtimestamp(now):%Y-%m-%d}.jsonl"
                with open(path, "a") as f:
                    f.write(json.dumps(row) + "\n")
                self.count += 1
            self._prune()
        except OSError as e:
            log.warning("timeline write failed (%s)", e)

    def thumbnail(self, jpeg: bytes | None) -> str | None:
        """Save a small copy of a camera picture, rarely. Returns its file name, or None if skipped."""
        if not (self.enabled and self.cfg.thumbnails and jpeg):
            return None
        now = self._clock()
        if now - self._last_thumb < self.cfg.thumb_every_s:
            return None
        small = self._shrink(jpeg)
        if small is None:
            return None
        stamp = f"{datetime.fromtimestamp(now):%Y%m%d-%H%M%S}-{int(now * 1000) % 1000:03d}"
        try:
            with self._lock:
                (self.dir / "thumbs").mkdir(parents=True, exist_ok=True)
                name, n = f"{stamp}.jpg", 1
                while (self.dir / "thumbs" / name).exists():   # never overwrite an earlier picture
                    name, n = f"{stamp}-{n}.jpg", n + 1
                (self.dir / "thumbs" / name).write_bytes(small)
            self._last_thumb = now
            return name
        except OSError as e:
            log.warning("timeline thumbnail failed (%s)", e)
            return None

    def _shrink(self, jpeg: bytes) -> bytes | None:
        try:
            import cv2
            import numpy as np
            img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                return None
            w = self.cfg.thumb_width
            if img.shape[1] > w:
                img = cv2.resize(img, (w, max(1, round(img.shape[0] * w / img.shape[1]))))
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 60])
            return buf.tobytes() if ok else None
        except Exception:
            return None   # no OpenCV (or a damaged picture): events are still recorded, just without pictures

    # ---- keeping it tidy ------------------------------------------------------------------------------
    def _files(self) -> list[Path]:
        if not self.dir.exists():
            return []
        return [p for p in self.dir.rglob("*") if p.is_file()]

    def _prune(self, force: bool = False) -> None:
        now = self._clock()
        if not force and now - self._last_prune < 600:
            return
        self._last_prune = now
        try:
            files = self._files()
            cutoff = now - self.cfg.keep_days * 86400
            for p in files:
                if p.stat().st_mtime < cutoff:
                    p.unlink(missing_ok=True)
            files = sorted(self._files(), key=lambda p: p.stat().st_mtime)
            total = sum(p.stat().st_size for p in files)
            limit = self.cfg.max_mb * 1024 * 1024
            for p in files:                       # oldest first, pictures before the event files they belong to
                if total <= limit:
                    break
                total -= p.stat().st_size
                p.unlink(missing_ok=True)
        except OSError as e:
            log.warning("timeline cleanup failed (%s)", e)

    def clear(self) -> int:
        """Delete everything. Returns how many files were removed."""
        removed = 0
        with self._lock:
            for p in self._files():
                try:
                    p.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed

    # ---- reading --------------------------------------------------------------------------------------
    def recent(self, n: int = 20) -> list[dict]:
        rows: list[dict] = []
        try:
            for path in sorted(self.dir.glob("*.jsonl"), reverse=True):
                lines = path.read_text().splitlines()
                for line in reversed(lines):
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
                    if len(rows) >= n:
                        return list(reversed(rows))
        except OSError:
            pass
        return list(reversed(rows))

    @staticmethod
    def format(row: dict) -> str:
        rest = " ".join(f"{k}={v}" for k, v in row.items() if k not in ("t", "kind"))
        return f"{row.get('t', '')[11:23]} {row.get('kind', '?'):<8} {rest}"

    def describe(self) -> str:
        if not self.enabled:
            return "off (/timeline on)"
        size = sum(p.stat().st_size for p in self._files()) / 1e6 if self.dir.exists() else 0
        return (f"recording to logs/timeline ({self.count} events this run, {size:.1f} MB used, kept {self.cfg.keep_days:g} days, "
                f"pictures {'on' if self.cfg.thumbnails else 'off'})")
