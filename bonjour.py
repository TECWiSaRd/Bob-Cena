"""Announce Bob on the local network (Bonjour / mDNS) so the Bob app on a phone or computer can find him without typing an address.

Uses a tool that is already there: `avahi-publish` on the Pi (package avahi-utils), `dns-sd` on a Mac. It keeps that program
running, restarts it if it ends, and stops it when Bob stops. If neither tool exists, the app still works: type the address.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading

log = logging.getLogger("bob.bonjour")

SERVICE = "_bob._tcp"


class Bonjour:
    def __init__(self, name: str, port: int, txt: dict, which=shutil.which, popen=subprocess.Popen, retry_s: float = 10.0):
        self.name, self.port, self.txt = name, int(port), dict(txt)
        self._which, self._popen, self._retry = which, popen, retry_s
        self._proc = None
        self._halt = threading.Event()
        self.tool = ""

    def command(self) -> list[str] | None:
        records = [f"{k}={v}" for k, v in self.txt.items()]
        if self._which("avahi-publish"):
            self.tool = "avahi-publish"
            return ["avahi-publish", "-s", self.name, SERVICE, str(self.port), *records]
        if self._which("dns-sd"):
            self.tool = "dns-sd"
            return ["dns-sd", "-R", self.name, SERVICE, "local", str(self.port), *records]
        return None

    def start(self) -> bool:
        cmd = self.command()
        if cmd is None:
            log.warning("Bonjour is off: install avahi-utils (sudo apt-get install -y avahi-utils) so the app can find Bob by itself; "
                        "until then, type his address in the app")
            return False
        threading.Thread(target=self._keep_running, args=(cmd,), name="bonjour", daemon=True).start()
        return True

    def _keep_running(self, cmd: list[str]) -> None:
        announced = False
        while not self._halt.is_set():
            try:
                self._proc = self._popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if not announced:
                    log.info("Bonjour: announcing '%s' as %s on port %d (%s)", self.name, SERVICE, self.port, self.tool)
                    announced = True
                while not self._halt.is_set() and self._proc.poll() is None:
                    self._halt.wait(1.0)
            except OSError as e:
                log.warning("Bonjour couldn't start %s (%s)", cmd[0], e)
            if self._halt.wait(self._retry):
                break

    def stop(self) -> None:
        self._halt.set()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
