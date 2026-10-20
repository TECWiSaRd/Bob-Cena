"""Powering the Pi off from Bob's console, the shared console or the phone dashboard.

Powering off is different from /quit: nobody can switch the Pi back on from a distance, someone has to unplug
and replug it. So it takes two steps, `/shutdown` and then `/shutdown confirm` within a short time, by the same
person. Bob then stops the wheels, says goodbye, shuts himself down cleanly, and only then asks the operating
system to power off. Claude has no way to do this; only people can.

The Pi needs permission to power off without a password. A Pi set up with Raspberry Pi Imager usually has it;
otherwise run ./install_power.sh once (it adds one narrow rule: this exact command, nothing else).
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time

log = logging.getLogger("bob.power")


def _run(args: list[str], timeout: float = 10.0) -> tuple[int, str]:
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)
    return done.returncode, (done.stdout + done.stderr).strip()


class PowerControl:
    def __init__(self, cfg, sim: bool = False, run=_run, which=shutil.which, clock=time.monotonic, euid=os.geteuid):
        self.cfg, self.sim, self._run, self._which, self._clock, self._euid = cfg, sim, run, which, clock, euid
        self._pending: dict[str, float] = {}      # who asked -> when their confirmation window ends
        self._lock = threading.Lock()
        self.requested = False                    # set once a confirmed shutdown is under way

    # ---- who ----------------------------------------------------------------------------------------
    def allows(self, role: str) -> bool:
        return bool(self.cfg.enabled and role in self.cfg.who)

    # ---- can this account power the Pi off? ----------------------------------------------------------------
    def command(self) -> list[str]:
        path = self._which("shutdown") or "/usr/sbin/shutdown"
        base = [path, "-h", "now"]
        return base if self._euid() == 0 else ["sudo", "-n", *base]

    def capable(self) -> tuple[bool, str]:
        if self.sim:
            return True, "simulated"
        cmd = self.command()
        if cmd[0] != "sudo":
            return True, "running as root"
        code, out = self._run(["sudo", "-n", "-l", *cmd[2:]])
        if code == 0:
            return True, "allowed by sudo"
        return False, ("this account isn't allowed to power the Pi off without a password. "
                       "Run ./install_power.sh on the Pi once")

    # ---- the two steps -------------------------------------------------------------------------------------
    def request(self, who: str) -> str:
        ok, why = self.capable()
        if not ok:
            return f"can't power off: {why}"
        with self._lock:
            self._pending[who] = self._clock() + self.cfg.confirm_seconds
        what = "Bob will quit and the (simulated) Pi would power off" if self.sim else \
            "This powers the Pi OFF, and it can't be switched back on from here: someone has to unplug and replug the power"
        return f"{what}. To go ahead type /shutdown confirm within {self.cfg.confirm_seconds:g} seconds (/shutdown cancel to stop)."

    def confirm(self, who: str) -> tuple[bool, str]:
        with self._lock:
            until = self._pending.pop(who, None)
            if until is None or self._clock() > until:
                return False, "type /shutdown first, then /shutdown confirm"
            self.requested = True
        return True, ""

    def cancel(self, who: str) -> str:
        with self._lock:
            had = self._pending.pop(who, None) is not None
        return "cancelled" if had else "nothing to cancel"

    # ---- the actual power-off, after Bob has shut down cleanly -------------------------------------------------
    def execute(self) -> tuple[bool, str]:
        if not self.requested:
            return False, "no shutdown was requested"
        if self.sim:
            return True, "[sim] the Pi would power off now"
        code, out = self._run(self.command(), timeout=30)
        if code != 0:
            log.error("Power-off failed (%s): %s", code, out)
            return False, f"power-off failed: {out or code}"
        return True, "power-off started"
