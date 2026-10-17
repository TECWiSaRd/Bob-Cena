"""Hardware layer: drive servos, camera and speaker.

Each part falls back to a simulated stand-in when its hardware or library is
missing (or with --sim), so Bob can be bench-tested without wheels touching
the ground.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import logging
import math
import os
import queue
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path

log = logging.getLogger("bob.hw")


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


# Hardware PWM through the kernel's sysfs interface. GPIO12/13 (and 18/19) are the
# Pi's PWM0 pins, so pulses come from the PWM peripheral instead of software timing.
PWM_CHIP = Path("/sys/class/pwm/pwmchip0")
PWM_CHANNELS = {12: 0, 13: 1, 18: 0, 19: 1}
PWM_OVERLAY = "dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4"


class _SysfsPwm:
    """One hardware PWM channel. Duty is set in nanoseconds."""

    def __init__(self, pin: int, period_ns: int):
        if pin not in PWM_CHANNELS:
            raise ValueError(f"GPIO{pin} has no hardware PWM (use 12/13 or 18/19)")
        if not PWM_CHIP.exists():
            raise FileNotFoundError(
                f"{PWM_CHIP} missing - add '{PWM_OVERLAY}' to /boot/firmware/config.txt and reboot")
        self.period_ns = int(period_ns)
        self._enabled = False
        channel = PWM_CHANNELS[pin]
        self._dir = PWM_CHIP / f"pwm{channel}"
        if not self._dir.exists():
            (PWM_CHIP / "export").write_text(str(channel))
        deadline = time.monotonic() + 3.0  # udev grants write access a moment after export
        while True:
            try:
                self._write("enable", 0)
                self._write("duty_cycle", 0)
                self._write("period", self.period_ns)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.05)

    def _write(self, name: str, value: int) -> None:
        (self._dir / name).write_text(str(int(value)))

    def set_duty_ns(self, ns: float) -> None:
        self._write("duty_cycle", min(max(ns, 0), self.period_ns))
        if not self._enabled:
            self._write("enable", 1)
            self._enabled = True

    def disable(self) -> None:
        if self._enabled:
            self._write("enable", 0)
            self._enabled = False

    def close(self) -> None:
        try:
            self.disable()
            (PWM_CHIP / "unexport").write_text(self._dir.name.removeprefix("pwm"))
        except OSError:
            pass


class SysfsServo(_SysfsPwm):
    """Minimal drop-in for gpiozero.Servo: .value in -1..1, or None to stop pulses."""

    def __init__(self, pin: int, min_ms: float, max_ms: float):
        super().__init__(pin, 20_000_000)  # 50 Hz
        self._min, self._max = int(min_ms * 1e6), int(max_ms * 1e6)
        self._value = 0.0

    @property
    def value(self):
        return self._value if self._enabled else None

    @value.setter
    def value(self, v):
        if v is None:
            self.disable()
            return
        self._value = clamp(v, -1.0, 1.0)
        self.set_duty_ns(self._min + (self._value + 1) / 2 * (self._max - self._min))


class _HwDuty:
    def __init__(self, pin: int, hz: int):
        self._ch = _SysfsPwm(pin, 1e9 / hz)

    def set(self, duty: float) -> None:
        self._ch.set_duty_ns(clamp(duty, 0.0, 1.0) * self._ch.period_ns)

    def close(self) -> None:
        self._ch.close()


class _SwDuty:
    """gpiozero software PWM, capped at 1 kHz. Fine for DC motors (no timing precision needed)."""

    def __init__(self, pin: int, hz: int):
        from gpiozero import PWMOutputDevice
        self._dev = PWMOutputDevice(pin, frequency=min(hz, 1000), initial_value=0)

    def set(self, duty: float) -> None:
        self._dev.value = clamp(duty, 0.0, 1.0)

    def close(self) -> None:
        self._dev.close()


def _make_duty(pin: int, hz: int):
    try:
        pwm = _HwDuty(pin, hz)
        log.info("Motor PWM on GPIO%d: hardware, %d Hz", pin, hz)
        return pwm
    except Exception as e:
        log.info("Motor PWM on GPIO%d: software 1 kHz (%s)", pin, e)
        return _SwDuty(pin, hz)


class DcMotor:
    """One TB6612FNG channel. .value in -1..1 (sign = direction); None or 0 stops.

    `trim_key` names the config field (left_trim / right_trim) that scales this
    motor's final power, so drift correction still works at low speeds.
    """

    def __init__(self, pwm_pin: int, in1_pin: int, in2_pin: int, cfg, trim_key: str):
        from gpiozero import DigitalOutputDevice
        self._cfg, self._trim_key = cfg, trim_key  # read live, so /minduty and /trim apply at once
        self._devs: list = []
        self._value = None
        self._dir = 0
        try:
            self._pwm = _make_duty(pwm_pin, cfg.dc_pwm_hz)
            self._devs.append(self._pwm)
            self._in1 = DigitalOutputDevice(in1_pin, initial_value=bool(cfg.dc_brake))
            self._devs.append(self._in1)
            self._in2 = DigitalOutputDevice(in2_pin, initial_value=bool(cfg.dc_brake))
            self._devs.append(self._in2)
        except Exception:
            self._release()
            raise

    def _release(self) -> None:
        for dev in self._devs:
            try:
                dev.close()
            except Exception:
                pass
        self._devs = []

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, v):
        if not v:
            self._value, self._dir = None, 0
            self._pwm.set(0.0)
            self._in1.value = self._in2.value = bool(self._cfg.dc_brake)  # brake: both high; coast: both low
            return
        v = clamp(v, -1.0, 1.0)
        direction = 1 if v > 0 else -1
        if direction != self._dir:
            # IN1/IN2 change one at a time and pass through short-brake; with the PWM at zero that is harmless.
            self._pwm.set(0.0)
            self._in1.value, self._in2.value = (direction > 0), (direction < 0)
            self._dir = direction
        self._value = v
        # Motors don't turn below a minimum duty: map 0..1 onto min..1, then apply this wheel's trim.
        lo = self._cfg.dc_min_duty
        duty = (lo + (1 - lo) * abs(v)) * (1 + getattr(self._cfg, self._trim_key))
        self._pwm.set(clamp(duty, 0.0, 1.0))

    def close(self) -> None:
        if self._devs:
            self.value = None
            self._release()


class Tb6612:
    """TB6612FNG motor driver: two motors plus the standby pin that powers the outputs down."""

    def __init__(self, cfg):
        from gpiozero import DigitalOutputDevice
        self._stby = self.left = self.right = None
        try:
            self._stby = DigitalOutputDevice(cfg.dc_standby, initial_value=False)  # low = outputs off
            self.left = DcMotor(cfg.dc_left_pwm, cfg.dc_left_in1, cfg.dc_left_in2, cfg, "left_trim")
            self.right = DcMotor(cfg.dc_right_pwm, cfg.dc_right_in1, cfg.dc_right_in2, cfg, "right_trim")
            self.standby(True)
        except Exception:
            self.close()  # free whatever was claimed so a retry doesn't hit "pin in use"
            raise
        log.info("TB6612FNG ready (left PWM GPIO%d, right PWM GPIO%d, STBY GPIO%d)",
                 cfg.dc_left_pwm, cfg.dc_right_pwm, cfg.dc_standby)

    def standby(self, on: bool) -> None:
        """on=True enables the outputs; False cuts power to both motors."""
        self._stby.value = bool(on)

    def close(self) -> None:
        for motor in (self.left, self.right):
            if motor is not None:
                motor.close()
        if self._stby is not None:
            self.standby(False)
            self._stby.close()
            self._stby = None


class Drive:
    """Two drive motors, one per long side (tank steering): continuous-rotation
    servos (type = "servo") or DC motors on a TB6612FNG (type = "dc").

    Every motion has a deadline; a watchdog thread stops the wheels when it
    passes, so a crash or a hung call can never leave Bob driving.
    """

    def __init__(self, cfg, sim: bool = False, ranger=None):
        self.cfg = cfg
        self.sim = sim
        self.ranger = ranger        # distance sensor: forward moves stop short of obstacles
        self.stop_reason = ""       # why the last move was refused or cut short by the reflex
        self.on_event = None        # optional callback(reason) when the reflex refuses or stops a move (the timeline)
        self._forward = False
        self.speed_cap = cfg.max_speed
        self.estop = threading.Event()
        self.on_estop = None  # callback set by the controller
        self._lock = threading.Lock()
        self._deadline = 0.0
        self._moving = False
        self._left = self._right = self._button = self._board = None
        self._closed = False
        self._released = False
        if not sim:
            try:
                self._left, self._right = self._make_servos()
            except Exception as e:
                log.error("DRIVE UNAVAILABLE (%s) - the wheels will NOT move; simulating", e)
                self.sim = True
        if cfg.estop_button_pin >= 0 and not self.sim:
            try:
                from gpiozero import Button
                self._button = Button(cfg.estop_button_pin)
                self._button.when_pressed = lambda: self.on_estop and self.on_estop("button")
                log.info("Physical E-stop button on GPIO%d", cfg.estop_button_pin)
            except Exception as e:
                log.warning("E-stop button unavailable (%s)", e)
        threading.Thread(target=self._watchdog, name="drive-watchdog", daemon=True).start()

    def _make_servos(self):
        cfg = self.cfg
        if cfg.type == "dc":
            self._board = Tb6612(cfg)
            return self._board.left, self._board.right
        mode = cfg.pwm  # auto | hardware | pigpio | software
        if mode in ("auto", "hardware"):
            left = None
            try:
                left = SysfsServo(cfg.left_pin, cfg.min_pulse_ms, cfg.max_pulse_ms)
                right = SysfsServo(cfg.right_pin, cfg.min_pulse_ms, cfg.max_pulse_ms)
                log.info("Using hardware PWM on GPIO%d/%d (steady pulses)", cfg.left_pin, cfg.right_pin)
                return left, right
            except Exception as e:
                if left:
                    left.close()
                if mode == "hardware":
                    raise
                log.warning("Hardware PWM not available (%s)", e)

        from gpiozero import Servo

        kw = dict(
            initial_value=None,  # detached = no pulses = no creep
            min_pulse_width=cfg.min_pulse_ms / 1000,
            max_pulse_width=cfg.max_pulse_ms / 1000,
        )
        if mode in ("auto", "pigpio"):
            try:
                from gpiozero.pins.pigpio import PiGPIOFactory
                kw["pin_factory"] = PiGPIOFactory()
                log.info("Using pigpio for jitter-free servo PWM")
            except Exception as e:
                log.warning("pigpio not available (%s); software PWM will make servos jitter", e)
        else:
            log.warning("Using software PWM: servos may jitter")
        return Servo(cfg.left_pin, **kw), Servo(cfg.right_pin, **kw)

    def _apply(self, left: float, right: float) -> None:
        if self._released:
            return
        cap, cfg = self.speed_cap, self.cfg
        l, r = clamp(left, -1, 1) * cap, clamp(right, -1, 1) * cap
        dc = cfg.type == "dc"
        if cfg.left_invert:
            l = -l
        if cfg.right_invert:
            r = -r
        if self.sim:
            log.debug("[sim] wheels L=%+.2f R=%+.2f", l, r)
            return
        if not dc:  # servos: trim shifts the pulse (DC motors apply theirs inside DcMotor, after min-duty)
            l = clamp(l + cfg.left_trim, -1, 1) if l else 0
            r = clamp(r + cfg.right_trim, -1, 1) if r else 0
        self._left.value = None if l == 0 else l
        self._right.value = None if r == 0 else r

    @property
    def moving(self) -> bool:
        return self._moving

    def start(self, left: float, right: float, seconds: float) -> bool:
        """Run the wheels for up to `seconds` without blocking. False if E-stopped."""
        if self.estop.is_set() or self._closed:
            return False
        seconds = clamp(seconds, 0.0, self.cfg.max_move_seconds)
        forward = left + right > 0.05
        with self._lock:
            self.stop_reason = ""
            if forward and (cm := self._obstacle()) is not None:
                self.stop_reason = f"obstacle {cm:.0f} cm ahead - refused to drive forward"
                self._halt_locked()
                self._emit(self.stop_reason)
                return False
            if seconds <= 0 or (left == 0 and right == 0):
                self._halt_locked()  # nothing to run: never energize without a deadline to stop at
                return True
            self._apply(left, right)
            self._deadline = time.monotonic() + seconds
            self._moving = True
            self._forward = forward
        return True

    def move(self, left: float, right: float, seconds: float) -> float:
        """Blocking move. Returns how long the wheels actually ran."""
        t0 = time.monotonic()
        if not self.start(left, right, seconds):
            return 0.0
        while self._moving and not self.estop.is_set() and not self._closed:
            time.sleep(0.02)
        return time.monotonic() - t0

    def _obstacle(self):
        return self.ranger.too_close() if self.ranger else None

    def _halt_locked(self) -> None:
        self._apply(0, 0)
        self._moving = False
        self._deadline = 0.0

    def stop(self) -> None:
        with self._lock:
            self._halt_locked()

    def emergency_stop(self) -> None:
        self.estop.set()
        self.stop()
        if self._board:
            self._board.standby(False)  # also cut the driver's outputs

    def clear_estop(self) -> None:
        if self._board:
            self._board.standby(True)
        self.estop.clear()

    def _watchdog(self) -> None:
        while True:
            time.sleep(0.02)
            with self._lock:  # check and act under one lock, so a newer move can't be cancelled by mistake
                if self._moving and (self.estop.is_set() or time.monotonic() >= self._deadline):
                    self._halt_locked()
                elif self._moving and self._forward and (cm := self._obstacle()) is not None:
                    self.stop_reason = f"obstacle {cm:.0f} cm ahead - stopped"
                    self._halt_locked()
                    self._emit(self.stop_reason)

    def _emit(self, reason: str) -> None:
        """Tell the timeline, from a helper thread so file writing can never delay the wheels."""
        cb = self.on_event
        if cb:
            threading.Thread(target=cb, args=(reason,), daemon=True).start()

    def close(self) -> None:
        self._closed = True  # refuse new moves before the hardware goes away
        self.stop()
        if self._board:  # closes both motors and drops STBY
            self._board.close()
            devices = (self._button,)
        else:
            devices = (self._left, self._right, self._button)
        for dev in devices:
            if dev is not None:
                dev.close()
        self._released = True


class _CsiSource:
    """Ribbon-cable Pi camera module via picamera2."""

    name = "Pi camera module"

    def __init__(self, cfg):
        from libcamera import Transform
        from picamera2 import Picamera2

        self._cam = Picamera2()  # raises if no camera is attached
        flip = cfg.rotate_180
        self._cam.configure(self._cam.create_video_configuration(
            main={"size": (cfg.width, cfg.height), "format": "RGB888"},  # RGB888 is B,G,R in memory: what OpenCV expects
            transform=Transform(hflip=flip, vflip=flip),
        ))
        self._cam.options["quality"] = cfg.jpeg_quality
        self.start()
        time.sleep(1.0)  # let auto-exposure settle

    def start(self):
        self._cam.start()

    def stop(self):
        self._cam.stop()

    def jpeg(self) -> bytes | None:
        buf = io.BytesIO()
        self._cam.capture_file(buf, format="jpeg")
        return buf.getvalue()

    def frame(self):
        """Latest frame as a BGR numpy array."""
        return self._cam.capture_array("main")

    def close(self):
        self._cam.close()


class _UsbSource:
    """USB webcam via V4L2 + OpenCV. A reader thread keeps the newest frame so
    captures are never stale (V4L2 otherwise hands back old buffered frames)."""

    name = "USB camera"

    def __init__(self, cfg):
        import cv2  # apt: python3-opencv

        self._cv2, self.cfg = cv2, cfg
        self._cap = None
        self._frame = None
        self._ts = 0.0
        self._run = threading.Event()
        self._thread = None
        self._open()
        self.start()
        # Fail now, not later, if the device opens but never delivers frames.
        deadline = time.monotonic() + 3.0
        while self._frame is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if self._frame is None:
            self.close()
            raise RuntimeError(f"/dev/video{cfg.device} opened but sent no frames")
        time.sleep(0.5)  # let auto-exposure settle

    def _open(self):
        cv2, cfg = self._cv2, self.cfg
        cap = cv2.VideoCapture(cfg.device, cv2.CAP_V4L2)
        if not cap.isOpened():
            raise RuntimeError(f"can't open /dev/video{cfg.device}")
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))  # raw YUYV is slow over USB
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.height)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._cap = cap

    def _reader(self):
        while self._run.is_set():
            ok, frame = self._cap.read()
            if ok:
                self._frame, self._ts = frame, time.monotonic()
            else:
                time.sleep(0.05)

    def start(self):
        if self._thread and self._thread.is_alive():  # a previous stop() timed out; let it finish first
            self._thread.join(3)
        if self._cap is None:
            self._open()
        self._frame = None
        self._run.set()
        self._thread = threading.Thread(target=self._reader, name="usb-camera", daemon=True)
        self._thread.start()

    def stop(self):
        self._run.clear()
        if self._thread:
            self._thread.join(3)
            if self._thread.is_alive():  # releasing mid-read can crash; try again on the next stop/close
                log.warning("USB camera reader is still busy; leaving the device open for now")
                return
        if self._cap is not None:
            self._cap.release()  # releasing the device turns the camera (and its LED) off
            self._cap = None
        self._frame = None

    def frame(self):
        frame = self._frame
        if frame is None or time.monotonic() - self._ts > 2.0:
            return None
        return self._cv2.rotate(frame, self._cv2.ROTATE_180) if self.cfg.rotate_180 else frame

    def jpeg(self) -> bytes | None:
        frame = self._frame
        if frame is None or time.monotonic() - self._ts > 2.0:
            return None
        cv2 = self._cv2
        if self.cfg.rotate_180:
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.cfg.jpeg_quality])
        return buf.tobytes() if ok else None

    def close(self):
        self.stop()


class Camera:
    """Front camera. cfg.source: "auto" (module first, then USB), "csi" or "usb"."""

    def __init__(self, cfg, sim: bool = False):
        self.cfg = cfg
        self._src = None
        self._lock = threading.Lock()
        self.enabled = True
        if sim:
            log.info("[sim] camera disabled - Bob is blind")
            return
        order = {"csi": [_CsiSource], "usb": [_UsbSource]}.get(cfg.source, [_CsiSource, _UsbSource])
        for factory in order:
            try:
                self._src = factory(cfg)
                log.info("Camera ready: %s (%dx%d)", self._src.name, cfg.width, cfg.height)
                return
            except Exception as e:
                log.warning("%s unavailable (%s)", factory.name, e)
        log.warning("No working camera - Bob is blind")

    @property
    def available(self) -> bool:
        return self._src is not None

    def set_enabled(self, on: bool) -> bool:
        """Operator switch. Off stops the sensor itself, not just frame capture.

        Returns False if the camera could not be switched on (it then stays off).
        """
        with self._lock:
            if self._src is not None and on != self.enabled:
                try:
                    self._src.start() if on else self._src.stop()
                except Exception as e:
                    log.warning("Camera %s failed: %s", "start" if on else "stop", e)
                    if on:
                        return False
            self.enabled = on
            return True

    def capture_jpeg(self) -> bytes | None:
        if self._src is None or not self.enabled:
            return None
        with self._lock:
            return self._src.jpeg()

    def grab_bgr(self):
        """A fresh frame as a BGR numpy array for local vision (following, calibration), or None."""
        if self._src is None or not self.enabled:
            return None
        with self._lock:
            return self._src.frame()

    def close(self) -> None:
        if self._src is not None:
            if self.enabled:
                self._src.stop()
            self._src.close()


# name -> [(frequency Hz, seconds)]; 0 Hz = silence
SOUNDS = {
    "beep": [(880, 0.12)],
    "chirp": [(660, 0.05), (880, 0.05), (1320, 0.09)],
    "happy": [(523, 0.1), (659, 0.1), (784, 0.1), (1047, 0.22)],
    "sad": [(440, 0.2), (370, 0.2), (294, 0.4)],
    "question": [(500, 0.1), (800, 0.2)],
    "alert": [(1200, 0.1), (0, 0.06), (1200, 0.1), (0, 0.06), (1200, 0.1)],
    "startup": [(392, 0.08), (523, 0.08), (659, 0.08), (784, 0.25)],
}
_RATE = 22050


def _synth(path: Path, notes) -> None:
    frames = bytearray()
    for freq, dur in notes:
        n = int(_RATE * dur)
        for i in range(n):
            env = min(1.0, i / 200, (n - i) / 200)  # short fades avoid clicks
            v = 0.0 if freq == 0 else 0.4 * env * math.sin(2 * math.pi * freq * i / _RATE)
            frames += struct.pack("<h", int(v * 32767))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_RATE)
        w.writeframes(bytes(frames))


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str, min_chars: int = 25) -> list[str]:
    """Split speech into sentences so the first can play while the rest is generated.
    Very short pieces are merged into the next one to avoid choppy pauses."""
    pieces, buf = [], ""
    for part in _SENTENCE_END.split(text.strip()):
        buf = f"{buf} {part}".strip()
        if len(buf) >= min_chars:
            pieces.append(buf)
            buf = ""
    if buf:
        if pieces and len(buf) < min_chars:
            pieces[-1] = f"{pieces[-1]} {buf}"
        else:
            pieces.append(buf)
    return pieces or [text]


class Audio:
    """Speaker: sound effects via aplay; speech via Piper (natural) with espeak-ng as the fallback."""

    def __init__(self, cfg, sound_dir: Path, sim: bool = False, voice_dir: Path | None = None):
        self.cfg = cfg
        self.muted = False
        self.active = False   # True while sound is playing, so the microphone can ignore Bob himself
        self.duck = contextlib.nullcontext   # replaced by the music system: lowers the music while Bob speaks
        self.last_end = 0.0
        self._lock = threading.Lock()
        self._voice_lock = threading.Lock()
        self._voice = None  # Piper voice, loaded once and kept in memory
        self.voice_dir = voice_dir or sound_dir.parent / "voices"
        self.sim = sim or shutil.which("aplay") is None
        if self.sim and not sim:
            log.warning("aplay not found - audio simulated")
        sound_dir.mkdir(parents=True, exist_ok=True)
        self._sounds = {}
        for name, notes in SOUNDS.items():
            path = sound_dir / f"{name}.wav"
            if not path.exists():
                _synth(path, notes)
            self._sounds[name] = path
        self._engines = self._pick_engines()
        if "piper" in self._engines and not self.sim:
            threading.Thread(target=self._warm_up, name="piper-warmup", daemon=True).start()

    def _piper_model(self) -> str | None:
        """The configured voice as something `piper -m` accepts, or None if its files are missing."""
        model = self.cfg.piper_model
        if not model:
            return None
        path = Path(model) if model.endswith(".onnx") else self.voice_dir / f"{model}.onnx"
        if path.exists():
            return str(path)
        log.warning("Piper voice %s not found - run: .venv/bin/python -m piper.download_voices "
                    "--data-dir %s %s", model, self.voice_dir, model)
        return None

    def _pick_engines(self) -> list[str]:
        engines = []
        if self.cfg.tts == "piper":
            if importlib.util.find_spec("piper") is None:
                log.info("Piper not installed - using espeak-ng for speech")
            elif self._piper_model():
                engines.append("piper")
        for engine in ("espeak-ng", "espeak"):
            if shutil.which(engine):
                engines.append(engine)
                break
        if not engines and not self.sim:
            log.warning("No TTS engine found (install espeak-ng) - speech is log-only")
        else:
            log.info("Speech engine: %s", engines[0] if engines else "none")
        return engines

    def _player(self) -> str:
        """pw-play plays through PipeWire, so Bob's voice mixes with Bluetooth/AirPlay music instead of fighting
        it for the device. aplay writes to the sound card directly (or through PipeWire's ALSA bridge)."""
        want = getattr(self.cfg, "player", "auto")
        if want in ("aplay", "pw-play"):
            return want
        now = time.monotonic()
        cached = getattr(self, "_player_cache", None)
        if cached and now - cached[0] < 30:
            return cached[1]
        choice = "aplay"
        if shutil.which("pw-play") and shutil.which("pw-cli"):
            try:
                if subprocess.run(["pw-cli", "info", "0"], capture_output=True, timeout=3).returncode == 0:
                    choice = "pw-play"   # PipeWire is running for this user
            except (OSError, subprocess.TimeoutExpired):
                pass
        self._player_cache = (now, choice)
        return choice

    def _play(self, path) -> None:
        if self._player() == "pw-play":
            cmd = ["pw-play", str(path)]
        else:
            cmd = ["aplay", "-q"] + (["-D", self.cfg.device] if self.cfg.device else []) + [str(path)]
        subprocess.run(cmd, timeout=60, capture_output=True, check=True)

    def play(self, name: str) -> str:
        if name not in self._sounds:
            raise ValueError(f"unknown sound {name!r}")
        if self.muted:
            return "speaker muted by operator; sound not played"
        if self.sim:
            return "played (simulated)"
        with self._lock:
            self.active = True
            try:
                self._play(self._sounds[name])
            finally:
                self.active, self.last_end = False, time.monotonic()
        return "played"

    def _get_voice(self):
        with self._voice_lock:
            if self._voice is None:
                from piper import PiperVoice
                model = self._piper_model()
                if not model:
                    raise RuntimeError("Piper voice files are missing")
                t0 = time.monotonic()
                self._voice = PiperVoice.load(model)
                log.info("Piper voice loaded in %.1fs", time.monotonic() - t0)
            return self._voice

    def _warm_up(self) -> None:
        """Load the voice and run one throwaway sentence, so the first real one isn't slow."""
        try:
            with self._lock:
                voice = self._get_voice()
                with wave.open(io.BytesIO(), "wb") as w:
                    voice.synthesize_wav("Hello.", w)
        except Exception as e:
            log.warning("Piper unavailable (%s) - using espeak-ng", e)
            if "piper" in self._engines:
                self._engines.remove("piper")

    def _synthesize(self, engine: str, text: str, wav: str) -> None:
        if engine == "piper":
            with wave.open(wav, "wb") as w:
                self._get_voice().synthesize_wav(text, w)
        else:
            cmd = [engine, "-v", self.cfg.voice, "-s", str(self.cfg.speed_wpm), "-w", wav, "--stdin"]
            subprocess.run(cmd, input=text.encode(), timeout=60, capture_output=True, check=True)

    def _speak(self, engine: str, text: str) -> float:
        """Synthesize sentence by sentence while the previous one plays. Returns time to first audio."""
        pieces = split_sentences(text) if engine == "piper" else [text]
        paths: queue.Queue = queue.Queue(maxsize=2)
        failed: list[Exception] = []
        t0 = time.monotonic()
        first = []

        def player():
            while (path := paths.get()) is not None:
                try:
                    if not failed:
                        first or first.append(time.monotonic() - t0)
                        self._play(path)
                except Exception as e:
                    failed.append(e)
                finally:
                    Path(path).unlink(missing_ok=True)

        thread = threading.Thread(target=player, name="speaker", daemon=True)
        thread.start()
        try:
            for piece in pieces:
                if failed:
                    break
                fd, path = tempfile.mkstemp(suffix=".wav")
                os.close(fd)
                try:
                    self._synthesize(engine, piece, path)
                except BaseException:
                    Path(path).unlink(missing_ok=True)
                    raise
                paths.put(path)
        finally:
            paths.put(None)
            thread.join()
        if failed:
            raise failed[0]
        return first[0] if first else 0.0

    def say(self, text: str) -> str:
        text = " ".join(text.split())[:400]
        if self.muted:
            return "speaker muted by operator; words were logged only"
        if self.sim or not self._engines:
            return "spoken (simulated)"
        with self._lock, self.duck():   # the music falls while Bob speaks and returns afterwards
            self.active = True  # include synthesis time: a late echo isn't worth risking
            t0 = time.monotonic()
            try:
                for i, engine in enumerate(list(self._engines)):
                    try:
                        first = self._speak(engine, text)
                        log.info("Spoke with %s: first audio after %.1fs, done in %.1fs",
                                 engine, first, time.monotonic() - t0)
                        break
                    except Exception as e:
                        if i == len(self._engines) - 1:
                            raise
                        log.warning("%s failed (%s); falling back to %s", engine,
                                    getattr(e, "stderr", b"").decode(errors="replace")[-200:] or e,
                                    self._engines[i + 1])
            finally:
                self.active, self.last_end = False, time.monotonic()
        return "spoken"
