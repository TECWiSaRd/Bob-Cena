"""Drive Bob with a BBC micro:bit.

Three ways to connect (see manual 27):
  - USB: plug a micro:bit running microbit/bob_remote.py into the Pi (it shows up as a serial port)
  - radio: plug in a second micro:bit running microbit/bob_bridge.py and carry the handheld one around
  - Bluetooth (transport = "ble"): a V2 micro:bit running microbit/bob_remote_ble.ts talks straight to the Pi's own Bluetooth
Either way the Pi hears short text lines, one per line (USB/radio at 115200 baud):

    D x y [key]   tilt: x = turn, y = forward, each -100..100. Sent only while the A button is held (a dead man's switch)
    M [key]       tap B: switch manual driving on or off (turning it on pauses the AI)
    E             A and B together: EMERGENCY STOP. Always works, needs no key
    T [key]       touch the logo (micro:bit V2): push-to-talk
    C [key]       hold B for three seconds: release the emergency stop. Off unless [microbit] allow_clear = true

and Bob sends back a line the micro:bit shows as a picture:  MODE idle | drive | estop

Safety is the same as the keyboard and the Xbox controller: the speed cap still applies, every tilt only moves Bob in a short pulse
that stops on its own, and when the micro:bit goes quiet or is unplugged the wheels stop. Claude has no tool for any of this.

The micro:bit's radio is NOT secure: anyone nearby with a micro:bit on the same radio group hears it. That is why the emergency stop
needs no key, and why a `key` (a short word that the micro:bit program also knows) can be required for everything else.
"""
from __future__ import annotations

import asyncio
import logging
import os
import queue
import threading
import time

log = logging.getLogger("bob.microbit")

PULSE_S = 0.4              # each tilt message moves Bob this long, so silence means a stop
QUIET_S = 0.6              # no message for this long while moving: stop now rather than wait for the pulse to end
MAX_LINE = 64              # longer lines are noise
WHO = "microbit"           # the micro:bit is its own driver, like the controller
TILT = 100.0

# Nordic UART service: what the micro:bit's Bluetooth UART looks like. "TX" is micro:bit -> Pi (notifications), "RX" is Pi -> micro:bit.
UART_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
UART_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
BLE_SCAN_S = 8.0
BLE_CONNECT_S = 15.0


def find_devices() -> list[str]:
    """Serial ports that are a micro:bit (by USB name), e.g. /dev/serial/by-id/usb-ARM_BBC_micro:bit_CMSIS-DAP_...-if01."""
    base = "/dev/serial/by-id"
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return []
    return [f"{base}/{n}" for n in names if "micro" in n.lower() and "bit" in n.lower()]


def parse(line: str):
    """One line from the micro:bit as (verb, numbers, key), or None when it isn't something we understand."""
    parts = line.strip().split()
    if not parts or len(line) > MAX_LINE:
        return None
    verb, rest = parts[0].upper(), parts[1:]
    if verb == "D":
        if len(rest) < 2:
            return None
        try:
            x, y = float(rest[0]), float(rest[1])
        except ValueError:
            return None
        if x != x or y != y:                                   # NaN
            return None
        key = rest[2] if len(rest) > 2 else ""
        return "D", (max(-TILT, min(TILT, x)) / TILT, max(-TILT, min(TILT, y)) / TILT), key
    if verb in ("M", "T", "C"):
        return verb, (), rest[0] if rest else ""
    if verb == "E":
        return "E", (), ""
    return None


class BleLink:
    """A Bluetooth connection to a micro:bit that looks like a serial port: read(n) / write(bytes) / close().

    bleak (the Bluetooth library) is asynchronous, so it gets its own thread with its own event loop; the rest of Bob stays
    simple and blocking. [bleak] is a parameter so tests can hand in a pretend one."""

    def __init__(self, name: str = "", address: str = "", bleak=None):
        self.name, self.address = name.strip().lower(), address.strip().lower()
        self._bleak = bleak
        self._q: queue.Queue = queue.Queue()
        self._gone = threading.Event()
        self._client = None
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="microbit-ble", daemon=True)

    def matches(self, name: str | None, address: str | None) -> bool:
        """Is this advertisement the micro:bit we want? An address wins; else the name must contain what was asked for."""
        if self.address:
            return (address or "").lower() == self.address
        n = (name or "").lower()
        return n.startswith("bbc micro:bit") and self.name in n

    async def _connect(self) -> None:
        bleak = self._bleak
        if bleak is None:
            import bleak                                           # imported late so tests and a Mac don't need it
        found = await bleak.BleakScanner.find_device_by_filter(
            lambda dev, adv: self.matches(getattr(adv, "local_name", None) or dev.name, dev.address), timeout=BLE_SCAN_S)
        if found is None:
            raise OSError("no micro:bit found over Bluetooth (is it on, and not already connected to a phone?)")
        client = bleak.BleakClient(found, disconnected_callback=lambda _c: self._gone.set())
        await client.connect()
        await client.start_notify(UART_TX, lambda _s, data: self._q.put(bytes(data)))
        self._client = client

    def open(self) -> "BleLink":
        self._thread.start()
        try:
            asyncio.run_coroutine_threadsafe(self._connect(), self._loop).result(BLE_SCAN_S + BLE_CONNECT_S)
        except Exception as e:
            self.close()
            raise OSError(str(e) or e.__class__.__name__) from e
        return self

    def read(self, n: int) -> bytes:
        try:
            return self._q.get(timeout=0.05)
        except queue.Empty:
            if self._gone.is_set():
                raise OSError("Bluetooth link lost")
            return b""

    def write(self, data: bytes) -> None:
        if self._gone.is_set() or self._client is None:
            raise OSError("Bluetooth link lost")
        asyncio.run_coroutine_threadsafe(self._client.write_gatt_char(UART_RX, data, response=False), self._loop).result(2.0)

    def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                asyncio.run_coroutine_threadsafe(client.disconnect(), self._loop).result(3.0)
            except Exception:
                pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread.is_alive():
            self._thread.join(timeout=3.0)
        if not self._thread.is_alive() and not self._loop.is_closed():
            self._loop.close()


class MicroBit(threading.Thread):
    def __init__(self, cfg, ctrl, find=find_devices, opener=None, clock=time.monotonic):
        super().__init__(name="microbit", daemon=True)
        if cfg.transport not in ("usb", "ble"):
            raise ValueError(f'[microbit] transport must be "usb" or "ble", not {cfg.transport!r}')
        self.cfg, self.ctrl, self._find, self._clock = cfg, ctrl, find, clock
        self._open = opener or self._open_serial
        self.halt = threading.Event()
        self.connected = ""                      # the port's name while a micro:bit is attached
        self._moving = False
        self._last_tilt = 0.0
        self._port = None
        self._wrote = ""

    # ---- what the lines mean (no threads, no ports: easy to test) -----------------------------------------------
    @staticmethod
    def shape(value: float, deadzone: float) -> float:
        mag = abs(value)
        if mag <= deadzone:
            return 0.0
        return (1.0 if value > 0 else -1.0) * min(1.0, (mag - deadzone) / (1.0 - deadzone))

    def _keyed(self, key: str) -> bool:
        want = self.cfg.key
        return not want or key == want

    def mode(self) -> str:
        ctrl = self.ctrl
        if ctrl.drive.estop.is_set():
            return "estop"
        return "drive" if ctrl.driving_for(WHO) else "idle"

    def reply(self) -> None:
        """Tell the micro:bit what Bob is doing now, when that has changed."""
        mode = self.mode()
        if mode != self._wrote and self._port is not None:
            try:
                self._port.write(f"MODE {mode}\n".encode())
                self._wrote = mode
            except Exception:
                pass

    def line(self, text: str) -> None:
        msg = parse(text)
        if msg is None:
            return
        verb, nums, key = msg
        ctrl, cfg = self.ctrl, self.cfg
        if verb == "E":
            ctrl.estop("micro:bit")
            self._moving = False
        elif not self._keyed(key):
            log.warning("micro:bit: ignored %s with the wrong key", verb)
        elif verb == "D":
            if not cfg.drive or not ctrl.driving_for(WHO) or ctrl.drive.estop.is_set():
                return
            turn, throttle = self.shape(nums[0], cfg.deadzone), self.shape(nums[1], cfg.deadzone)
            left, right = throttle + turn, throttle - turn
            peak = max(abs(left), abs(right), 1.0)
            self._last_tilt = self._clock()
            if left or right:
                self._moving = True
                ctrl.manual(left / peak * cfg.speed, right / peak * cfg.speed, PULSE_S)
            elif self._moving:
                self._moving = False
                ctrl.drive.stop()
        elif verb == "M":
            if not cfg.drive:
                return
            if ctrl.driving_for(WHO):
                ctrl.drive.stop()
                ctrl.leave_drive(WHO)
                self._moving = False
                log.info("micro:bit: left manual drive - AI still paused, /resume to hand back control")
            else:
                log.info("micro:bit: %s", ctrl.handle("/drive", by=WHO))
        elif verb == "T":
            log.info("%s", ctrl.listener.ptt_toggle())
        elif verb == "C":
            if cfg.allow_clear:
                log.info("micro:bit: %s", ctrl.handle("/clear"))
            else:
                log.info("micro:bit: asked to release the emergency stop; that is off ([microbit] allow_clear), use /clear")
        self.reply()

    def tick(self) -> None:
        """Called about every 50 ms: stop if the tilt messages dried up."""
        if self._moving and self._clock() - self._last_tilt > QUIET_S:
            self._moving = False
            self.ctrl.drive.stop()
        self.reply()

    def lost(self) -> None:
        self._moving = False
        self._wrote = ""
        self._port = None
        self.ctrl.drive.stop()

    # ---- the port -----------------------------------------------------------------------------------------------
    def _open_serial(self, path: str):
        if self.cfg.transport == "ble":
            return BleLink(self.cfg.ble_name, self.cfg.ble_address).open()
        import serial                                              # pyserial: imported late so tests and a Mac don't need it
        return serial.Serial(path, self.cfg.baud, timeout=0.05)

    def _wanted(self) -> list[str]:
        if self.cfg.transport == "ble":
            return ["bluetooth"]
        if self.cfg.device and self.cfg.device != "auto":
            return [self.cfg.device]
        return self._find()

    def _read(self, port, buf: bytearray) -> bool:
        """Handle what has arrived. False when the micro:bit has gone."""
        try:
            data = port.read(256)
        except Exception:
            return False
        if data:
            buf.extend(data)
            while b"\n" in buf:
                raw, _, rest = bytes(buf).partition(b"\n")
                buf[:] = rest
                self.line(raw.decode("ascii", "ignore"))
            if len(buf) > MAX_LINE * 4:                            # no newline in sight: junk
                buf.clear()
        self.tick()
        return True

    def run(self) -> None:
        waited = False
        while not self.halt.is_set():
            port = None
            for path in self._wanted():
                try:
                    port = self._open(path)
                except Exception as e:
                    log.debug("micro:bit %s: %s", path, e)
                    continue
                self.connected = os.path.basename(path)
                log.info("micro:bit connected: %s (B = manual drive, hold A and tilt = drive, A+B = emergency stop)", self.connected)
                break
            if port is None:
                if not waited:
                    log.info("micro:bit: waiting for one (%s)",
                             "switch it on, within a few metres" if self.cfg.transport == "ble" else "plug it in by USB, or plug in the bridge micro:bit")
                    waited = True
                self.halt.wait(2.0)
                continue
            waited = False
            self._port = port
            buf = bytearray()
            try:
                while not self.halt.is_set() and self._read(port, buf):
                    pass
            except Exception:
                log.exception("micro:bit reader crashed")
            finally:
                try:
                    port.close()
                except Exception:
                    pass
                self.lost()
                if self.connected:
                    log.warning("micro:bit disconnected: wheels stopped")
                self.connected = ""
            self.halt.wait(1.0)

    def stop(self) -> None:
        self.halt.set()

    def describe(self) -> str:
        return f"connected: {self.connected}" if self.connected else "no micro:bit found"
