"""Tell someone when Bob needs attention, and notice when he can't tell you himself.

Two separate things, both optional, both set up with a link kept in `.env` (never in config.toml, so it can't be committed):

  HEARTBEAT_URL   a "dead man's switch" such as healthchecks.io. Bob pings it every minute with a line of vital signs. If the
                  pings STOP (the Pi froze, lost power or Wi-Fi), that service messages you. A frozen Pi can't report itself;
                  a missing heartbeat can.
  NOTIFY_URL      a push-notification address such as an ntfy topic (https://ntfy.sh/your-secret-topic). Bob sends short
                  messages here: started after an unexpected stop, emergency stop, camera stuck, overheating or weak power,
                  low disk or memory, an update, the Pi being powered off.

Nothing from the camera or the microphone is ever sent, only short status text. Messages are queued and sent from a
background thread, so a slow or unreachable service can never hold Bob up.
"""
from __future__ import annotations

import logging
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger("bob.alerts")

ALL_KINDS = ("start", "restart", "stopped", "estop", "camera", "power", "update", "vitals")


def _valid_url(url: str) -> bool:
    p = urlparse(url)
    return p.scheme in ("http", "https") and bool(p.netloc)


def _host(url: str) -> str:
    return urlparse(url).netloc if url else "not set"


def vitals(base: Path | str = ".", run=None, read=None) -> dict:
    """A few numbers about the Pi's health. Anything that can't be read here is left out."""
    def _run(args):
        try:
            done = subprocess.run(args, capture_output=True, text=True, timeout=3)
            return done.stdout if done.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None

    def _read(path):
        try:
            return Path(path).read_text()
        except OSError:
            return None

    run, read = run or _run, read or _read
    out: dict = {}
    load = (read("/proc/loadavg") or "").split()
    if load:
        out["load"] = float(load[0])
    m = re.search(r"MemAvailable:\s+(\d+) kB", read("/proc/meminfo") or "")
    if m:
        out["mem_mb"] = int(m.group(1)) // 1024
    m = re.search(r"temp=([\d.]+)", run(["vcgencmd", "measure_temp"]) or "")
    if m:
        out["temp_c"] = float(m.group(1))
    m = re.search(r"0x([0-9a-fA-F]+)", run(["vcgencmd", "get_throttled"]) or "")
    if m:
        out["throttled"] = int(m.group(1), 16)
    try:
        out["disk_gb"] = shutil.disk_usage(base).free / 1e9
    except OSError:
        pass
    return out


def vitals_line(v: dict) -> str:
    bits = []
    if "load" in v:
        bits.append(f"load {v['load']:.2f}")
    if "mem_mb" in v:
        bits.append(f"{v['mem_mb']} MB free")
    if "temp_c" in v:
        bits.append(f"{v['temp_c']:.0f} C")
    if "throttled" in v:
        bits.append(f"throttled 0x{v['throttled']:x}")
    if "disk_gb" in v:
        bits.append(f"disk {v['disk_gb']:.1f} GB free")
    return ", ".join(bits) or "no readings here"


def problems(v: dict) -> list[tuple[str, str]]:
    """(key, text) for each vital sign that needs attention."""
    out = []
    if v.get("temp_c", 0) >= 80:
        out.append(("hot", f"The Pi is hot ({v['temp_c']:.0f} C) and will slow itself down."))
    t = v.get("throttled", 0)
    if t & 0x1 or t & 0x4:
        out.append(("power", "The Pi reports under-voltage or throttling right now (weak power supply?)."))
    if "disk_gb" in v and v["disk_gb"] < 1:
        out.append(("disk", f"Only {v['disk_gb']:.1f} GB of disk space is left."))
    if "mem_mb" in v and v["mem_mb"] < 150:
        out.append(("memory", f"Only {v['mem_mb']} MB of memory is free."))
    return out


class Alerts:
    def __init__(self, cfg, name: str = "Bob", heartbeat_url: str = "", notify_url: str = "", base=".",
                 opener=urllib.request.urlopen, clock=time.monotonic, sample=vitals):
        self.cfg, self.name, self.base = cfg, name, Path(base)
        self.heartbeat_url, self.notify_url = heartbeat_url.strip(), notify_url.strip()
        self._open, self._clock, self._sample = opener, clock, sample
        self.problem = ""
        for what, url in (("HEARTBEAT_URL", self.heartbeat_url), ("NOTIFY_URL", self.notify_url)):
            if url and not _valid_url(url):
                self.problem = f"{what} in .env isn't a web address (it should start with https://)"
                log.error("Alerts: %s", self.problem)
        if self.problem:
            self.heartbeat_url = self.notify_url = ""
        self.enabled = bool(cfg.enabled and (self.heartbeat_url or self.notify_url))
        self._queue: queue.Queue = queue.Queue(maxsize=50)
        self._last_sent: dict[str, float] = {}
        self._halt = threading.Event()
        self._threads: list[threading.Thread] = []
        self.last_beat: float | None = None       # when the heartbeat last got through
        self.beat_error = ""
        self.sent = 0
        self.failed = 0
        self.log_errors_at = -1e9

    # ---- running ------------------------------------------------------------------------------------
    def start(self) -> None:
        if not self.enabled:
            return
        for target, name in ((self._send_loop, "alerts-send"), (self._beat_loop, "alerts-beat")):
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            self._threads.append(t)
        log.info("Alerts on (heartbeat: %s, notifications: %s)", _host(self.heartbeat_url), _host(self.notify_url))

    def stop(self, wait: float = 3.0) -> None:
        """Let queued messages go out (briefly), then stop."""
        end = self._clock() + wait
        while self.enabled and self._queue.unfinished_tasks and self._clock() < end:
            time.sleep(0.05)
        self._halt.set()

    # ---- sending ------------------------------------------------------------------------------------
    def notify(self, kind: str, text: str, priority: str = "default", force: bool = False) -> bool:
        """Queue a push message. Each kind is limited to one per `cooldown_s`, so a loop can't flood your phone."""
        if not self.enabled or not self.notify_url:
            return False
        if kind in ALL_KINDS and kind not in self.cfg.notify and not force:
            return False
        now = self._clock()
        if not force and now - self._last_sent.get(kind, -1e9) < self.cfg.cooldown_s:
            return False
        self._last_sent[kind] = now
        try:
            self._queue.put_nowait((text, priority, kind))
        except queue.Full:
            return False
        return True

    def _post(self, url: str, body: str, headers: dict | None = None) -> None:
        req = urllib.request.Request(url, data=body.encode()[:2000], headers=headers or {}, method="POST")
        with self._open(req, timeout=8) as resp:
            resp.read(200)

    def _send_loop(self) -> None:
        while not self._halt.is_set():
            try:
                text, priority, kind = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._post(self.notify_url, text, {"Title": self.name, "Priority": priority, "Tags": kind})
                self.sent += 1
            except (OSError, urllib.error.URLError, ValueError) as e:
                self.failed += 1
                self._complain(f"couldn't send a notification ({e})")
            finally:
                self._queue.task_done()

    def _complain(self, text: str) -> None:
        now = self._clock()
        if now - self.log_errors_at > 300:                       # one complaint every 5 minutes at most
            self.log_errors_at = now
            log.warning("Alerts: %s", text)

    # ---- the heartbeat and the health checks --------------------------------------------------------
    def beat(self) -> None:
        """One heartbeat, plus a look at the vital signs."""
        v = self._sample(self.base)
        if self.heartbeat_url:
            try:
                self._post(self.heartbeat_url, f"{self.name} alive: {vitals_line(v)}")
                self.last_beat, self.beat_error = self._clock(), ""
            except (OSError, urllib.error.URLError, ValueError) as e:
                self.beat_error = str(e)
                self._complain(f"heartbeat didn't get through ({e})")
        if "vitals" in self.cfg.notify:
            for key, text in problems(v):                          # each problem is reported at most once an hour
                tag = "vitals:" + key
                if self._clock() - self._last_sent.get(tag, -1e9) > 3600:
                    self._last_sent[tag] = self._clock()
                    self.notify("vitals", text, priority="high", force=True)

    def _beat_loop(self) -> None:
        while not self._halt.is_set():
            try:
                self.beat()
            except Exception:
                log.exception("Alerts heartbeat crashed")
            self._halt.wait(max(10.0, self.cfg.heartbeat_every_s))

    # ---- for /alerts --------------------------------------------------------------------------------
    def describe(self) -> str:
        if not self.cfg.enabled:
            return "off ([alerts] enabled = false)"
        if self.problem:
            return self.problem
        if not (self.heartbeat_url or self.notify_url):
            return "on, but neither HEARTBEAT_URL nor NOTIFY_URL is set in .env (manual 23)"
        beat = "heartbeat: not set" if not self.heartbeat_url else (
            f"heartbeat to {_host(self.heartbeat_url)}: " + (f"last got through {self._clock() - self.last_beat:.0f}s ago"
                                                           if self.last_beat is not None else "not yet")
            + (f" (problem: {self.beat_error})" if self.beat_error else ""))
        notes = f"notifications to {_host(self.notify_url)}: {self.sent} sent, {self.failed} failed" if self.notify_url else "notifications: not set"
        return f"{beat}; {notes}; tells you about: {', '.join(self.cfg.notify)}"


# ---- noticing an unexpected stop -----------------------------------------------------------------------
def mark_running(flag: Path) -> bool:
    """Write the 'running' flag. Returns True if the previous run did NOT shut down cleanly (crash, freeze, power cut)."""
    unclean = flag.exists()
    try:
        flag.write_text(f"{os.getpid()} {time.time():.0f}\n")
    except OSError:
        pass
    return unclean


def clear_running(flag: Path) -> None:
    try:
        flag.unlink()
    except OSError:
        pass
