"""/check: one report on whether Bob is ready to run.

Nothing here moves the wheels, records sound or calls the Claude API. It reads the state Bob already has, takes
one camera picture, and asks the Pi a few quick questions (temperature, power, Wi-Fi, disk).
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
from pathlib import Path

OK, WARN, FAIL, OFF = "ok", "WARN", "FAIL", "off"


def _run(args: list[str], timeout: float = 3.0) -> str | None:
    """Output of a command, or None if it isn't installed, fails, or takes too long."""
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return (done.stdout + done.stderr) if done.returncode == 0 else None


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def run_checks(ctrl, base: Path, run=_run, read=_read, which=shutil.which) -> list[tuple[str, str, str]]:
    """A list of (level, name, detail). `run`, `read` and `which` are replaced in tests."""
    out: list[tuple[str, str, str]] = []

    def add(level: str, name: str, detail: str) -> None:
        out.append((level, name, detail))

    # ---- Bob's own parts ------------------------------------------------------------------------------
    drive = ctrl.drive
    if drive.sim:
        add(WARN, "motors", "simulated: the wheels will NOT move (started with --sim, or the driver wasn't found; "
                            "look for DRIVE UNAVAILABLE in the log)")
    elif drive.estop.is_set():
        add(WARN, "motors", "ready, but the EMERGENCY STOP is on: /clear releases it")
    else:
        add(OK, "motors", f"{ctrl.cfg.drive.type} drive ready; speed cap {drive.speed_cap:.2f}")

    cam = ctrl.camera
    if not cam.available:
        add(FAIL, "camera", "none found: Bob is blind (lsusb / rpicam-hello --list-cameras)")
    elif not cam.enabled:
        add(WARN, "camera", "switched off: /camera on")
    else:
        jpeg = cam.capture_jpeg()
        if jpeg:
            add(OK, "camera", f"picture received ({len(jpeg) // 1024} KB)")
        else:
            add(FAIL, "camera", "found, but gave no picture")

    audio = ctrl.audio
    engines = list(getattr(audio, "_engines", []))
    if audio.sim:
        add(FAIL, "speaker", "aplay not found: all sound is simulated")
    elif not engines:
        add(FAIL, "speaker", "no speech engine: sounds work, speech is log-only (install espeak-ng)")
    elif ctrl.cfg.audio.tts == "piper" and "piper" not in engines:
        add(WARN, "speaker", f"speech works with {engines[0]}, but Piper isn't available (robotic voice)")
    elif audio.muted:
        add(WARN, "speaker", f"speech: {engines[0]}, but MUTED (/unmute)")
    else:
        add(OK, "speaker", f"speech: {engines[0]}")

    lis, mic = ctrl.listener, ctrl.cfg.mic
    if not lis.on:
        add(OFF, "microphone", "off (/listen on)")
    elif which("arecord") is None:
        add(FAIL, "microphone", "arecord isn't installed (sudo apt-get install alsa-utils)")
    elif importlib.util.find_spec("faster_whisper") is None:
        add(FAIL, "microphone", "faster-whisper isn't installed: Bob can't understand speech")
    else:
        note = f"{lis.describe()}; device {mic.device or 'default'}"
        if lis.wake_engine != "off" and lis._engine() != lis.wake_engine:
            add(WARN, "microphone", f"{note}; wake word '{lis.wake_engine}' unavailable, using '{lis._engine()}'")
        else:
            add(OK, "microphone", note)

    ranger = ctrl.ranger
    if not ctrl.cfg.sensor.enabled:
        add(OFF, "distance sensor", "not enabled in config.toml")
    elif not ranger.available:
        add(FAIL, "distance sensor", "enabled but not working: wiring, or the ECHO voltage divider")
    elif not ranger.enabled:
        add(WARN, "distance sensor", "reflex switched OFF: the wheels will not stop for obstacles (/range on)")
    else:
        add(OK, "distance sensor", ranger.describe())

    # ---- connections ------------------------------------------------------------------------------------
    st = ctrl.stream
    if st is None or getattr(st, "_httpd", None) is None:
        add(OFF, "stream", "not running")
    else:
        host, port = st._httpd.server_address[:2]
        if not st.token:
            add(WARN, "stream", f"on {host}:{port}, this Pi only (set BOB_STREAM_TOKEN to use it from other devices)")
        else:
            add(OK, "stream", f"on {host}:{port}, password protected; dashboard {'on' if st.dashboard_enabled else 'off'}")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        add(FAIL, "claude", "no ANTHROPIC_API_KEY: Bob can move when driven, but can't think")
    else:
        add(OK, "claude", f"key set; model {ctrl.cfg.brain.model}, effort {ctrl.cfg.brain.effort}"
                          + ("; AI paused" if not ctrl.controls.auto else ""))

    if ctrl.music is None:
        add(OFF, "music", "not enabled")
    elif ctrl.music.problems:
        for p in ctrl.music.problems:
            add(WARN, "music", p)
    else:
        add(OK, "music", "ready")

    if ctrl.radio is None:
        add(OFF, "radio", "enabled but not running (see the log)" if ctrl.cfg.radio.enabled else "not enabled")
    else:
        add(OK if ctrl.radio.connected else WARN, "radio", ctrl.radio.state)

    # ---- the Pi itself ----------------------------------------------------------------------------------
    temp = read("/sys/class/thermal/thermal_zone0/temp")
    if temp and temp.isdigit():
        c = int(temp) / 1000
        add(FAIL if c >= 80 else WARN if c >= 70 else OK, "temperature",
            f"{c:.0f} C" + (" (hot: it will slow itself down)" if c >= 70 else ""))
    else:
        add(OFF, "temperature", "not readable here")

    m = re.search(r"0x([0-9a-fA-F]+)", run(["vcgencmd", "get_throttled"]) or "")
    if m:
        bits = int(m.group(1), 16)
        labels = ((0, "under-voltage now"), (1, "frequency capped"), (2, "throttled now"),
                  (16, "under-voltage since boot"), (18, "throttled since boot"))
        found = [label for bit, label in labels if bits >> bit & 1]
        if found:
            add(WARN, "power", f"{', '.join(found)} (weak USB-C supply or cable?)")
        else:
            add(OK, "power", "no under-voltage")
    else:
        add(OFF, "power", "not readable here")

    try:
        free = shutil.disk_usage(base).free / 1e9
        add(FAIL if free < 1 else WARN if free < 3 else OK, "disk", f"{free:.1f} GB free")
    except OSError:
        add(OFF, "disk", "not readable")

    m = re.search(r"MemAvailable:\s+(\d+) kB", read("/proc/meminfo") or "")
    if m:
        mb = int(m.group(1)) // 1024
        add(WARN if mb < 200 else OK, "memory", f"{mb} MB available")

    link = run(["iw", "dev", "wlan0", "link"])
    sig = re.search(r"signal:\s*(-?\d+) dBm", link or "")
    if sig:
        dbm = int(sig.group(1))
        add(WARN if dbm < -75 else OK, "wi-fi", f"signal {dbm} dBm" + (" (weak)" if dbm < -75 else ""))
        if "on" in (run(["iw", "dev", "wlan0", "get", "power_save"]) or "").lower():
            add(WARN, "wi-fi power saving", "on: it causes slow or dropped SSH (manual 02, 'Keeping Wi-Fi responsive')")
    elif link is not None:
        add(WARN, "wi-fi", "not connected")
    else:
        add(OFF, "wi-fi", "not readable here (wired, or not a Pi)")

    home = getattr(ctrl, "home", None)
    if home is not None:
        level, detail = home.check()
        add(level, "home assistant", detail)

    ix = getattr(ctrl, "index", None)
    if ix is not None:
        if not ix.enabled:
            add(OFF, "search index", "off")
        elif ix.last_error:
            add(WARN, "search index", f"problem: {ix.last_error}")
        else:
            add(OK, "search index", ix.status().removeprefix("search index: "))

    tl = getattr(ctrl, "timeline", None)
    if tl is not None:
        add(OK if tl.enabled else OFF, "timeline", tl.describe())
    return out


def format_report(checks: list[tuple[str, str, str]]) -> str:
    width = max(len(name) for _, name, _ in checks)
    lines = [f"  {level:<4}  {name:<{width}}  {detail}" for level, name, detail in checks]
    bad = sum(1 for lv, *_ in checks if lv == FAIL)
    warn = sum(1 for lv, *_ in checks if lv == WARN)
    good = sum(1 for lv, *_ in checks if lv == OK)
    verdict = "ready to run" if not bad and not warn else "needs attention before he runs" if bad else "usable, with warnings"
    lines.append(f"  {good} ok, {warn} warning{'s' * (warn != 1)}, {bad} problem{'s' * (bad != 1)}: {verdict}")
    return "\n".join(lines)
