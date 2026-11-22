"""Control Bob from the Bob app over Bluetooth LE, for when there is no good Wi-Fi (an event, a field, a hotspot that dropped).

Two parts. BleCore is the protocol (blecodec.py describes the messages): it checks every message's signature and then does the same things the app's
Wi-Fi connection can do: a drive pulse, stop, status, a console command from the same short list, and the emergency stop. BleLink is the
radio: a small Bluetooth LE server (the `bless` package, on top of BlueZ) that hands what the app writes to BleCore and sends back its answers.

Safety: nothing here can make the wheels run for more than the 0.4 seconds a drive pulse lasts, so if the link drops he stops by himself; the
emergency stop works from the app at any time; and the speed cap, /pause, sleep mode and the other overrides apply exactly as for any other driving.
Claude has no way to use this.
"""
from __future__ import annotations

import asyncio
import hmac
import logging
import math
import os
import threading
import time

import blecodec

log = logging.getLogger("bob.ble")

PULSE_S = 0.4          # a drive pulse; the app sends them about four times a second
SESSION_S = 600.0      # how long a hello stays good without any signed message
MAX_FAILS = 8          # this many bad signatures in a minute and he ignores everything (but the emergency stop) for a minute
LOCK_S = 60.0
MAX_SESSIONS = 20


class BleCore:
    def __init__(self, cfg, controller, devices, run_command=None, label_of=None, clock=time.monotonic, nonce=lambda: os.urandom(8).hex()):
        self.cfg, self.ctrl, self.devices = cfg, controller, devices
        self.run_command = run_command or (lambda text, by=None: controller.handle(text, by=by, role="dashboard") or "")
        self.label_of = label_of or (lambda ident: ident)
        self._clock, self._nonce = clock, nonce
        self._lock = threading.Lock()
        self._sessions: dict[str, dict] = {}
        self._fails: list[float] = []
        self._locked_until = 0.0
        self._recent: list[float] = []
        self.last_message = 0.0
        self.messages = 0

    # ---- helpers -------------------------------------------------------------------
    def _rate_ok(self, now: float) -> bool:
        self._recent = [t for t in self._recent if now - t < 1.0]
        if len(self._recent) >= max(1.0, self.cfg.max_per_second):
            return False
        self._recent.append(now)
        return True

    def _fail(self, now: float) -> None:
        self._fails = [t for t in self._fails if now - t < 60.0] + [now]
        if len(self._fails) >= MAX_FAILS:
            self._locked_until = now + LOCK_S
            self._fails = []
            log.warning("Bluetooth: too many wrong signatures, ignoring commands for %d s", LOCK_S)

    def _estop(self) -> list[str]:
        self.ctrl.estop("bluetooth")
        return ["OK stopped"]

    # ---- one message ---------------------------------------------------------------
    def handle(self, line: str) -> list[str]:
        """What to send back (lines, possibly none) for one message from the app."""
        now = self._clock()
        line = line.strip()
        if not line:
            return []
        parts = line.split(" ", 4)
        cmd = parts[0].upper()
        with self._lock:
            if cmd == "E" and len(parts) == 1 and self.cfg.open_estop:
                return self._estop()                                   # always, even when busy or locked out: it only ever stops him
            if now < self._locked_until:
                return ["ERR locked"]
            if not self._rate_ok(now):
                return []
            if cmd == "H":
                return self._hello(parts, now)
            if cmd not in ("D", "S", "T", "C", "E"):
                return ["ERR what"]
            return self._signed(cmd, line, parts, now)

    def _hello(self, parts: list[str], now: float) -> list[str]:
        found = self.devices.ble_lookup(parts[1]) if len(parts) == 2 else None
        if found is None:
            self._fail(now)
            return ["ERR unknown device"]
        ident, key = found
        self._sessions = {d: s for d, s in self._sessions.items() if s["expires"] > now}
        if len(self._sessions) >= MAX_SESSIONS and parts[1] not in self._sessions:
            return ["ERR busy"]
        nonce = self._nonce()
        self._sessions[parts[1]] = {"nonce": nonce, "ctr": 0, "expires": now + SESSION_S, "ident": ident, "key": key}
        return [f"N {nonce}"]

    def _signed(self, cmd: str, line: str, parts: list[str], now: float) -> list[str]:
        # forms: D dev ctr l r mac | S dev ctr mac | T dev ctr mac | E dev ctr mac | C dev ctr mac text
        try:
            dev, ctr = parts[1], int(parts[2])
            if cmd == "D":
                words = line.split(" ")
                if len(words) != 6:
                    raise ValueError
                body, mac_given = f"D {words[3]} {words[4]}", words[5]
            elif cmd == "C":
                mac_given, text = parts[3], parts[4]
                body = f"C {text}"
            else:
                mac_given, body = parts[3], cmd
            if not 0 < ctr < 2 ** 31:
                raise ValueError
        except (IndexError, ValueError):
            return ["ERR what"]
        session = self._sessions.get(dev)
        if session is None or session["expires"] < now or self.devices.ble_lookup(dev) is None:
            self._sessions.pop(dev, None)                              # (a device that was unpaired loses its session at once)
            return ["ERR session"]                                     # the app should say hello again
        expected = blecodec.mac(session["key"], dev, session["nonce"], ctr, body)
        if not hmac.compare_digest(expected, str(mac_given)):
            self._fail(now)
            return ["ERR auth"]
        if ctr <= session["ctr"]:
            return []                                                  # old or repeated: ignored, not an error
        session["ctr"], session["expires"] = ctr, now + SESSION_S
        self.last_message, self.messages = now, self.messages + 1
        return self._do(cmd, body, session["ident"])

    def _do(self, cmd: str, body: str, ident: str) -> list[str]:
        c = self.ctrl
        if cmd == "E":
            return self._estop()
        if cmd == "S":
            c.drive.stop()
            return ["OK"]
        if cmd == "T":
            return [f"T e={int(c.drive.estop.is_set())} a={int(bool(c.controls.auto))} d={int(bool(c.drive_mode))} s={c.drive.speed_cap:.2f}"]
        if cmd == "D":
            try:
                _, l_txt, r_txt = body.split(" ")
                left, right = float(l_txt), float(r_txt)
            except ValueError:
                return ["ERR what"]
            if not (math.isfinite(left) and math.isfinite(right)):
                return ["ERR what"]
            left, right = max(-1.0, min(1.0, left)), max(-1.0, min(1.0, right))
            if left == 0 and right == 0:
                c.drive.stop()
                return []
            said = c.manual(left, right, PULSE_S)
            return [] if said.startswith("manual move") else [f"ERR {said[:80]}"]
        text = body[2:]                                                # "C <text>"
        out = self.run_command(text, by=f"app:{self.label_of(ident)}") or ""
        lines = [ln for ln in str(out).splitlines() if ln.strip()][:6]
        return [f"R {ln[:100]}" for ln in lines] or ["OK"]

    def status(self) -> str:
        now = self._clock()
        live = sum(1 for s in self._sessions.values() if s["expires"] > now)
        ago = "no message yet" if not self.last_message else f"last message {now - self.last_message:.0f}s ago"
        return f"{live} device{'s' * (live != 1)} said hello recently, {self.messages} signed messages, {ago}"


class BleLink(threading.Thread):
    """The Bluetooth LE server. Starts in its own thread; if the `bless` package or Bluetooth isn't there, it says so in the log and Bob carries on."""

    def __init__(self, core: BleCore, name: str, server_factory=None, properties=None):
        super().__init__(name="ble", daemon=True)
        self.core, self.local_name = core, (name or "Bob")[:8]
        self._factory, self._props = server_factory, properties
        self._stop_flag = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self.running = False
        self.error = ""

    def stop(self) -> None:
        self._stop_flag.set()
        loop, wake = self._loop, self._wake
        if loop is not None and wake is not None:
            try:
                loop.call_soon_threadsafe(wake.set)
            except RuntimeError:
                pass                                                   # the loop already finished: nothing left to stop

    def run(self) -> None:
        try:
            asyncio.run(self._main())
        except Exception as e:                                         # no Bluetooth adapter, BlueZ not running, bless not installed...
            self.error = str(e) or e.__class__.__name__
            log.warning("Bluetooth control is not running (%s). Needs: pip install bless, and BlueZ with an adapter (manual 31)", self.error)
        finally:
            self.running = False

    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        queue: asyncio.Queue = asyncio.Queue()
        assembler = blecodec.LineAssembler()
        if self._factory is None:
            from bless import BlessServer, GATTAttributePermissions, GATTCharacteristicProperties as P
            self._factory = lambda name, loop: BlessServer(name=name, loop=loop)
            self._props = (P.write | P.write_without_response, GATTAttributePermissions.writeable,
                           P.read | P.notify, GATTAttributePermissions.readable)
        rx_props, rx_perm, tx_props, tx_perm = self._props
        server = self._factory(self.local_name, self._loop)

        def on_write(characteristic, value, *_):
            for line in assembler.feed(bytes(value)):
                asyncio.ensure_future(self._process(line, queue))

        server.read_request_func = lambda characteristic, *_: characteristic.value
        server.write_request_func = on_write
        await server.add_new_service(blecodec.SERVICE)
        await server.add_new_characteristic(blecodec.SERVICE, blecodec.RX, rx_props, None, rx_perm)
        await server.add_new_characteristic(blecodec.SERVICE, blecodec.TX, tx_props, bytearray(b"ready\n"), tx_perm)
        await server.start()
        self.running = True
        log.info("Bluetooth control is on: look for '%s' in the Bob app (signed messages only)", self.local_name)
        try:
            while not self._stop_flag.is_set():
                try:
                    reply = await asyncio.wait_for(queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                for piece in blecodec.chunks(reply):
                    server.get_characteristic(blecodec.TX).value = bytearray(piece)
                    server.update_value(blecodec.SERVICE, blecodec.TX)
                    await asyncio.sleep(0.03)                          # notifications sent back to back can be dropped
        finally:
            await server.stop()

    async def _process(self, line: str, queue: asyncio.Queue) -> None:
        try:
            replies = await asyncio.get_running_loop().run_in_executor(None, self.core.handle, line)
        except Exception:
            log.exception("Bluetooth message failed")
            return
        for reply in replies:
            await queue.put(reply)
