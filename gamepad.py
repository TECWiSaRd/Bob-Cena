"""Drive Bob with an Xbox (or similar) controller.

Reads the Linux joystick interface (/dev/input/js0), so nothing extra needs installing: plug the controller in by USB,
or pair it over Bluetooth, and it appears. Default layout (the Xbox layout used by Linux's xpad driver):

    Start (Menu)    switch manual driving on or off (turning it on pauses the AI)
    left stick      drive: up/down forward and back, left/right turn
    LB (hold)       slow mode
    B               EMERGENCY STOP, always, even when not driving
    Back (View)     hold 1.5 s to release the emergency stop
    Y               hand control back to the AI (/resume)
    A               push-to-talk

Safety is the same as the keyboard: the speed cap still applies, a stick left off-centre only moves Bob in short
pulses that stop on their own, and if the controller disconnects or the program stops reading it the wheels stop.
"""
from __future__ import annotations

import glob
import logging
import os
import select
import struct
import threading
import time

log = logging.getLogger("bob.gamepad")

EVENT = struct.Struct("IhBB")          # time (ms), value, type, number: Linux's struct js_event
BUTTON, AXIS, INIT = 0x01, 0x02, 0x80
PULSE_S = 0.4                          # each drive command lasts this long, so a lost signal means a stop
TICK_S = 0.05
CLEAR_HOLD_S = 1.5


def find_devices(pattern: str = "/dev/input/js*") -> list[str]:
    return sorted(glob.glob(pattern))


def device_name(path: str) -> str:
    try:
        with open(f"/sys/class/input/{os.path.basename(path)}/device/name") as f:
            return f.read().strip()
    except OSError:
        return os.path.basename(path)


class Gamepad(threading.Thread):
    def __init__(self, cfg, ctrl, find=find_devices, opener=None, clock=time.monotonic):
        super().__init__(name="gamepad", daemon=True)
        self.cfg, self.ctrl, self._find, self._clock = cfg, ctrl, find, clock
        self._open = opener or (lambda path: os.open(path, os.O_RDONLY | os.O_NONBLOCK))
        self.halt = threading.Event()
        self.connected = ""                        # the controller's name while one is attached
        self.axes: dict[int, float] = {}
        self.buttons: dict[int, bool] = {}
        self._back_since: float | None = None
        self._moving = False

    # ---- what the sticks and buttons mean (no threads, no devices: easy to test) -----------------------------------
    @staticmethod
    def shape(value: float, deadzone: float) -> float:
        """Ignore small wobble, then rescale so full deflection is still 1.0."""
        mag = abs(value)
        if mag <= deadzone:
            return 0.0
        return (1.0 if value > 0 else -1.0) * min(1.0, (mag - deadzone) / (1.0 - deadzone))

    def wheels(self) -> tuple[float, float]:
        """(left, right) wheel speeds for the current stick position."""
        c = self.cfg
        turn = self.shape(self.axes.get(c.axis_turn, 0.0), c.deadzone)
        throttle = -self.shape(self.axes.get(c.axis_throttle, 0.0), c.deadzone)        # sticks report up as negative
        left, right = throttle + turn, throttle - turn
        peak = max(abs(left), abs(right), 1.0)
        scale = c.slow_factor if self.buttons.get(c.btn_slow) else 1.0
        return left / peak * scale, right / peak * scale

    def press(self, number: int) -> None:
        c, ctrl = self.cfg, self.ctrl
        if number == c.btn_estop:
            ctrl.estop("gamepad")
        elif number == c.btn_drive:
            if ctrl.drive_mode:
                ctrl.drive.stop()
                ctrl.drive_mode = False
                log.info("Gamepad: left manual drive - AI still paused, Y or /resume to hand back control")
            else:
                note = ctrl.handle("/drive")
                log.info("Gamepad: %s", note)
        elif number == c.btn_resume:
            log.info("Gamepad: %s", ctrl.handle("/resume"))
        elif number == c.btn_talk:
            log.info("%s", ctrl.listener.ptt_toggle())

    def event(self, kind: int, number: int, value: int) -> None:
        if kind & INIT:                              # the starting state sent on connect: remember, never act on it
            kind &= ~INIT
            if kind == AXIS:
                self.axes[number] = value / 32767.0
            elif kind == BUTTON:
                self.buttons[number] = bool(value)
            return
        if kind == AXIS:
            self.axes[number] = max(-1.0, min(1.0, value / 32767.0))
        elif kind == BUTTON:
            was = self.buttons.get(number, False)
            self.buttons[number] = bool(value)
            if number == self.cfg.btn_back:
                self._back_since = self._clock() if value else None
            if value and not was:
                self.press(number)

    def tick(self) -> None:
        """Called every 50 ms: send the current stick position as a short drive pulse, or stop."""
        ctrl, now = self.ctrl, self._clock()
        if self._back_since is not None and now - self._back_since >= CLEAR_HOLD_S:
            self._back_since = None
            log.info("Gamepad: %s", ctrl.handle("/clear"))
        if not ctrl.drive_mode or ctrl.drive.estop.is_set():
            self._moving = False
            return
        left, right = self.wheels()
        if left or right:
            self._moving = True
            ctrl.manual(left, right, PULSE_S)
        elif self._moving:
            self._moving = False
            ctrl.drive.stop()

    def lost(self) -> None:
        """The controller went away: stop at once, and forget the sticks."""
        self.axes.clear()
        self.buttons.clear()
        self._back_since, self._moving = None, False
        self.ctrl.drive.stop()

    # ---- the device ---------------------------------------------------------------------------------------------
    def _wanted(self) -> list[str]:
        if self.cfg.device and self.cfg.device != "auto":
            return [self.cfg.device]
        return self._find()

    def _read(self, fd: int) -> bool:
        """Handle everything waiting on the device. False when the controller has gone."""
        ready, _, _ = select.select([fd], [], [], TICK_S)
        if ready:
            try:
                data = os.read(fd, EVENT.size * 64)
            except BlockingIOError:
                data = None
            except OSError:
                return False
            if data == b"":
                return False
            for off in range(0, len(data or b"") - EVENT.size + 1, EVENT.size):
                _, value, kind, number = EVENT.unpack_from(data, off)
                self.event(kind, number, value)
        self.tick()
        return True

    def run(self) -> None:
        waited = False
        while not self.halt.is_set():
            paths = self._wanted()
            fd = None
            for path in paths:
                try:
                    fd = self._open(path)
                except OSError as e:
                    log.debug("gamepad %s: %s", path, e)
                    continue
                self.connected = device_name(path)
                log.info("Gamepad connected: %s (Start = manual drive, B = emergency stop)", self.connected)
                break
            if fd is None:
                if not waited:
                    log.info("Gamepad: waiting for a controller (plug one in, or pair it over Bluetooth)")
                    waited = True
                self.halt.wait(2.0)
                continue
            waited = False
            try:
                while not self.halt.is_set() and self._read(fd):
                    pass
            except Exception:
                log.exception("Gamepad reader crashed")
            finally:
                try:
                    os.close(fd)
                except OSError:
                    pass
                self.lost()
                if self.connected:
                    log.warning("Gamepad disconnected: wheels stopped")
                self.connected = ""
            self.halt.wait(1.0)

    def stop(self) -> None:
        self.halt.set()

    def describe(self) -> str:
        return f"connected: {self.connected}" if self.connected else "no controller found"
