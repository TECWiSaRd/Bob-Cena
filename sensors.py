"""HC-SR04 ultrasonic distance sensor, used as a hardware-level reflex: the wheels
refuse to drive forward into something closer than `stop_cm`, whatever Claude decided.

Wiring (the ECHO pin outputs 5 V, which can damage a Pi GPIO, so divide it down):

    sensor VCC  -> 5 V          sensor GND -> GND (common with the Pi)
    sensor TRIG -> GPIO23       (3.3 V logic is fine for TRIG)
    sensor ECHO -> 1 kOhm -> GPIO24 -> 2 kOhm -> GND     (the junction goes to GPIO24)

It sees a narrow cone straight ahead, so it misses thin, soft or angled objects.
"""
from __future__ import annotations

import logging

log = logging.getLogger("bob.sensor")


class RangeSensor:
    def __init__(self, cfg, sim: bool = False):
        self.cfg = cfg
        self.enabled = cfg.enabled      # /range off turns the reflex off for testing
        self.stop_cm = cfg.stop_cm
        self._dev = None
        self._fake: float | None = None  # tests and --sim
        if not cfg.enabled or sim:
            return
        try:
            from gpiozero import DistanceSensor
            self._dev = DistanceSensor(echo=cfg.echo_pin, trigger=cfg.trigger_pin,
                                       max_distance=cfg.max_cm / 100, queue_len=3)
            log.info("Distance sensor ready (trigger GPIO%d, echo GPIO%d, stops at %d cm)",
                     cfg.trigger_pin, cfg.echo_pin, cfg.stop_cm)
        except Exception as e:
            log.warning("Distance sensor unavailable (%s) - no obstacle reflex", e)

    @property
    def available(self) -> bool:
        return self._dev is not None or self._fake is not None

    @property
    def distance_cm(self) -> float | None:
        """Distance to the nearest thing ahead, or None if there's no working sensor."""
        if not self.enabled:
            return None
        if self._fake is not None:
            return self._fake
        if self._dev is None:
            return None
        try:
            return float(self._dev.distance) * 100
        except Exception:
            return None

    def too_close(self) -> float | None:
        """The distance in cm if something is inside the stop distance, else None."""
        d = self.distance_cm
        return d if d is not None and d < self.stop_cm else None

    def describe(self) -> str:
        d = self.distance_cm
        if not self.enabled:
            return "distance sensor off"
        if d is None:
            return "no distance sensor"
        if d >= self.cfg.max_cm * 0.98:
            return f"clear ahead (nothing within {self.cfg.max_cm} cm)"
        label = "OBSTACLE" if d < self.stop_cm else "ahead"
        return f"{label} {d:.0f} cm" + (" (the wheels refuse to go forward)" if d < self.stop_cm else "")

    def close(self) -> None:
        if self._dev is not None:
            self._dev.close()
