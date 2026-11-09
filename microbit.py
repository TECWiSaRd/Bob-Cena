"""Drive Bob with a BBC micro:bit.

Plug a micro:bit into the Pi by USB (it shows up as a serial port) running microbit/bob_remote.py, or plug in a second micro:bit
running microbit/bob_bridge.py and carry the handheld one around: they talk by the micro:bit's own radio. Either way the Pi hears
short text lines, one per line, 115200 baud:

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

import logging
import os
import threading
import time

log = logging.getLogger("bob.microbit")

PULSE_S = 0.4              # each tilt message moves Bob this long, so silence means a stop
QUIET_S = 0.6              # no message for this long while moving: stop now rather than wait for the pulse to end
MAX_LINE = 64              # longer lines are noise
WHO = "microbit"           # the micro:bit is its own driver, like the controller
TILT = 100.0


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


class MicroBit(threading.Thread):
    def __init__(self, cfg, ctrl, find=find_devices, opener=None, clock=time.monotonic):
        super().__init__(name="microbit", daemon=True)
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
        import serial                                              # pyserial: imported late so tests and a Mac don't need it
        return serial.Serial(path, self.cfg.baud, timeout=0.05)

    def _wanted(self) -> list[str]:
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
                    log.info("micro:bit: waiting for one (plug it in by USB, or plug in the bridge micro:bit)")
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
