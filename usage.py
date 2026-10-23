"""All-time Claude usage, counted from Bob's own API calls and kept in usage.json on the Pi.

Every thought reports how many tokens it used. Bob adds them up per day and per model, with the cost worked out from the
prices at the time of the call, so a later price change never rewrites history. The file is small (one entry per day per
model) and is saved at most every 30 seconds plus at shutdown, to spare the SD card; a crash can lose the last half minute.

This is an estimate of what Bob itself spent. Your real bill (other uses of the same API key, rounding) is on your
Anthropic account page. Usage from before this file existed isn't counted.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

log = logging.getLogger("bob.usage")

FIELDS = ("calls", "input", "output", "cache_write", "cache_read", "cost")
SAVE_EVERY = 30.0


def _blank() -> dict:
    return {k: 0 for k in FIELDS} | {"cost": 0.0}


def _short(n: float) -> str:
    n = float(n)
    for unit, size in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if n >= size:
            return f"{n / size:.1f}{unit}"
    return f"{n:.0f}"


class UsageLedger:
    def __init__(self, path: Path, today=date.today, clock=time.monotonic):
        self.path, self._today, self._clock = Path(path), today, clock
        self._lock = threading.Lock()
        self.days: dict[str, dict[str, dict]] = {}
        self.since = self._today().isoformat()
        self._dirty = False
        self._saved_at = clock()
        self._load()

    # ---- file ---------------------------------------------------------------------------------------
    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text())
            days = data["days"]
            if not isinstance(days, dict):
                raise ValueError("days is not a table")
            self.days = {d: {m: {k: v.get(k, 0) for k in FIELDS} for m, v in models.items()} for d, models in days.items()}
            self.since = str(data.get("since") or self.since)
        except FileNotFoundError:
            return
        except (OSError, ValueError, KeyError, AttributeError, TypeError) as e:
            bad = self.path.with_name(self.path.name + ".bad")
            try:
                os.replace(self.path, bad)
            except OSError:
                pass
            log.warning("usage.json was unreadable (%s): kept as %s and started a new count", e, bad.name)
            self.days = {}

    def save(self) -> None:
        with self._lock:
            if not self._dirty:
                return
            data = {"since": self.since, "days": self.days}
            tmp = self.path.with_name(self.path.name + ".tmp")
            try:
                tmp.write_text(json.dumps(data, indent=1))
                os.replace(tmp, self.path)
                self._dirty = False
                self._saved_at = self._clock()
            except OSError as e:
                log.warning("couldn't save usage.json (%s)", e)

    flush = save

    # ---- counting -----------------------------------------------------------------------------------
    def record(self, model: str, input_tokens: int, output_tokens: int, cache_write: int, cache_read: int, cost: float) -> None:
        with self._lock:
            row = self.days.setdefault(self._today().isoformat(), {}).setdefault(model, _blank())
            row["calls"] += 1
            row["input"] += int(input_tokens or 0)
            row["output"] += int(output_tokens or 0)
            row["cache_write"] += int(cache_write or 0)
            row["cache_read"] += int(cache_read or 0)
            row["cost"] += float(cost)
            self._dirty = True
            due = self._clock() - self._saved_at >= SAVE_EVERY
        if due:
            self.save()

    # ---- reporting ----------------------------------------------------------------------------------
    def total(self, first: str | None = None, last: str | None = None) -> dict:
        out = _blank()
        with self._lock:
            for day, models in self.days.items():
                if (first and day < first) or (last and day > last):
                    continue
                for row in models.values():
                    for k in FIELDS:
                        out[k] += row[k]
        return out

    def by_model(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        with self._lock:
            for models in self.days.values():
                for name, row in models.items():
                    acc = out.setdefault(name, _blank())
                    for k in FIELDS:
                        acc[k] += row[k]
        return out

    def report(self, session_cost: float = 0.0) -> str:
        today = self._today()
        iso = today.isoformat()
        periods = [("today", iso, iso),
                   ("last 7 days", (today - timedelta(days=6)).isoformat(), iso),
                   ("this month", today.replace(day=1).isoformat(), iso),
                   ("all time", None, None)]
        lines = [f"Claude usage, counted from Bob's own calls (an estimate; tracking since {self.since})",
                 f"  {'':<12} {'calls':>7} {'input':>8} {'output':>8} {'cached':>8} {'cost':>9}"]
        for label, first, last in periods:
            t = self.total(first, last)
            lines.append(f"  {label:<12} {t['calls']:>7} {_short(t['input']):>8} {_short(t['output']):>8} "
                         f"{_short(t['cache_read']):>8} {'$' + format(t['cost'], '.2f'):>9}")
        models = self.by_model()
        if models:
            lines.append("  by model, all time:")
            for name, t in sorted(models.items(), key=lambda kv: -kv[1]["cost"]):
                lines.append(f"    {name:<22} {t['calls']:>6} calls  ${t['cost']:.2f}")
        with self._lock:
            active = sum(1 for models in self.days.values() if any(r["calls"] for r in models.values()))
        total = self.total()
        if active > 1:
            lines.append(f"  about ${total['cost'] / active:.2f} per day Bob was in use ({active} days)")
        lines.append(f"  this run: ${session_cost:.3f}")
        lines.append("  Your real bill is on your Anthropic account page; other uses of the same key aren't counted here.")
        return "\n".join(lines)
