"""Distance sensors, used as a hardware-level reflex: the wheels refuse to drive forward into something closer than
`stop_cm`, whatever Claude decided. Two kinds are supported, alone or together (the nearer reading wins, because the
safe mistake is to stop):

  * HC-SR04 ultrasonic (below)
  * VL53L1X laser time-of-flight on I2C: VIN -> 3.3 V, GND -> GND, SDA -> GPIO2 (pin 3), SCL -> GPIO3 (pin 5).
    It needs `pip install vl53l1x` and I2C switched on (sudo raspi-config, Interface Options). It sees soft things
    ultrasonic misses, and misses glass and bright sunlight, which is why having both is a good idea.

Wiring (the ECHO pin outputs 5 V, which can damage a Pi GPIO, so divide it down):

    sensor VCC  -> 5 V          sensor GND -> GND (common with the Pi)
    sensor TRIG -> GPIO23       (3.3 V logic is fine for TRIG)
    sensor ECHO -> 1 kOhm -> GPIO24 -> 2 kOhm -> GND     (the junction goes to GPIO24)

It sees a narrow cone straight ahead, so it misses thin, soft or angled objects.
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger("bob.sensor")


class LaserReader:
    """Reads a VL53L1X over I2C in a background thread, so a slow or stuck I2C read can never hold up the wheels. A
    reading older than `stale_s` is treated as no reading."""

    def __init__(self, device, stale_s: float = 0.6, clock=time.monotonic):
        self._dev, self._stale, self._clock = device, stale_s, clock
        self._cm: float | None = None
        self._at = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="laser-range", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                mm = self._dev.get_distance()      # blocks until a reading; -1 means the measurement was rejected
            except Exception as e:
                log.debug("laser read failed: %s", e)
                self._cm = None
                self._stop.wait(0.2)
                continue
            self._cm = mm / 10 if mm is not None and mm > 0 else None
            self._at = self._clock()

    @property
    def distance_cm(self) -> float | None:
        if self._cm is None or self._clock() - self._at > self._stale:
            return None
        return self._cm

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)
        try:
            self._dev.stop_ranging()
        except Exception:
            pass


def open_laser(cfg):
    """A started VL53L1X, or raises."""
    import VL53L1X
    dev = VL53L1X.VL53L1X(i2c_bus=cfg.tof_bus, i2c_address=cfg.tof_address)
    dev.open()
    dev.start_ranging(2)                            # 2 = medium range
    return dev


class RangeSensor:
    def __init__(self, cfg, sim: bool = False, laser_factory=open_laser):
        self.cfg = cfg
        self.enabled = cfg.enabled      # /range off turns the reflex off for testing
        self.stop_cm = cfg.stop_cm
        self._dev = None
        self._fake: float | None = None  # tests and --sim
        self._laser: LaserReader | None = None
        self._fake_laser: float | None = None
        if not cfg.enabled or sim:
            return
        if cfg.ultrasonic:
            try:
                from gpiozero import DistanceSensor
                self._dev = DistanceSensor(echo=cfg.echo_pin, trigger=cfg.trigger_pin,
                                           max_distance=cfg.max_cm / 100, queue_len=3)
                log.info("Ultrasonic sensor ready (trigger GPIO%d, echo GPIO%d, stops at %d cm)",
                         cfg.trigger_pin, cfg.echo_pin, cfg.stop_cm)
            except Exception as e:
                log.warning("Ultrasonic sensor unavailable (%s)", e)
        if cfg.tof:
            try:
                self._laser = LaserReader(laser_factory(cfg))
                log.info("Laser sensor ready (I2C bus %d, address 0x%02x)", cfg.tof_bus, cfg.tof_address)
            except Exception as e:
                log.warning("Laser sensor unavailable (%s)", e)
        if not self.available:
            log.warning("No distance sensor is working - no obstacle reflex")

    @property
    def available(self) -> bool:
        return (self._dev is not None or self._fake is not None
                or self._laser is not None or self._fake_laser is not None)

    def _ultrasonic_cm(self) -> float | None:
        if self._fake is not None:
            return self._fake
        if self._dev is None:
            return None
        try:
            return float(self._dev.distance) * 100
        except Exception:
            return None

    def _laser_cm(self) -> float | None:
        if self._fake_laser is not None:
            return self._fake_laser
        if self._laser is None:
            return None
        d = self._laser.distance_cm
        return None if d is None else min(d, float(self.cfg.max_cm))

    @property
    def distance_cm(self) -> float | None:
        """Distance to the nearest thing ahead (the nearer of the working sensors), or None if none is working."""
        if not self.enabled:
            return None
        readings = [d for d in (self._ultrasonic_cm(), self._laser_cm()) if d is not None]
        return min(readings) if readings else None

    def too_close(self) -> float | None:
        """The distance in cm if something is inside the stop distance, else None."""
        d = self.distance_cm
        return d if d is not None and d < self.stop_cm else None

    def describe(self) -> str:
        d = self.distance_cm
        if not self.enabled:
            return "distance sensor off"
        if d is None:
            return "no reading right now" if self.available else "no distance sensor"
        if d >= self.cfg.max_cm * 0.98:
            return f"clear ahead (nothing within {self.cfg.max_cm} cm)"
        label = "OBSTACLE" if d < self.stop_cm else "ahead"
        text = f"{label} {d:.0f} cm" + (" (the wheels refuse to go forward)" if d < self.stop_cm else "")
        u, l = self._ultrasonic_cm(), self._laser_cm()
        if u is not None and l is not None:
            text += f" [ultrasonic {u:.0f}, laser {l:.0f}]"
        return text

    def close(self) -> None:
        if self._laser is not None:
            self._laser.close()
        if self._dev is not None:
            self._dev.close()
