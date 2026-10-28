"""The obstacle reflex with an ultrasonic sensor, a laser sensor, or both (fakes only: no hardware is touched)."""
import time
import unittest

from config import SensorConfig
from sensors import LaserReader, RangeSensor


class FakeLaser:
    def __init__(self, readings):
        self.readings = list(readings)
        self.stopped = False
        self.calls = 0

    def get_distance(self):
        self.calls += 1
        time.sleep(0.005)
        return self.readings[min(self.calls - 1, len(self.readings) - 1)]

    def stop_ranging(self):
        self.stopped = True


def sensor(**kw):
    cfg = SensorConfig(enabled=True, **kw)
    return RangeSensor(cfg, sim=True)


def wait_for(cond, seconds=2.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


class Combined(unittest.TestCase):
    def test_nearer_reading_wins(self):
        s = sensor(tof=True)
        s._fake, s._fake_laser = 120.0, 30.0
        self.assertEqual(s.distance_cm, 30.0)
        s._fake, s._fake_laser = 25.0, 90.0
        self.assertEqual(s.distance_cm, 25.0)
        self.assertIn("ultrasonic 25", s.describe())
        self.assertIn("laser 90", s.describe())

    def test_one_sensor_covers_for_the_other(self):
        s = sensor(tof=True)
        s._fake, s._fake_laser = None, 40.0
        self.assertEqual(s.distance_cm, 40.0)
        s._fake, s._fake_laser = 55.0, None
        self.assertEqual(s.distance_cm, 55.0)

    def test_reflex_trips_on_either(self):
        s = sensor(tof=True, stop_cm=15)
        s._fake, s._fake_laser = 100.0, 10.0       # only the laser sees it
        self.assertEqual(s.too_close(), 10.0)
        s._fake, s._fake_laser = 10.0, 100.0       # only the ultrasonic does
        self.assertEqual(s.too_close(), 10.0)
        s._fake, s._fake_laser = 100.0, 100.0
        self.assertIsNone(s.too_close())

    def test_switched_off_reports_nothing(self):
        s = sensor(tof=True)
        s._fake, s._fake_laser = 5.0, 5.0
        s.enabled = False
        self.assertIsNone(s.distance_cm)
        self.assertIsNone(s.too_close())

    def test_no_working_sensor_is_said_plainly(self):
        s = sensor()
        self.assertFalse(s.available)
        self.assertEqual(s.describe(), "no distance sensor")

    def test_a_sensor_with_no_reading_is_not_called_missing(self):
        s = sensor(tof=True)
        s._fake_laser = None
        s._laser = LaserReader(FakeLaser([-1]))
        try:
            self.assertTrue(s.available)
            self.assertEqual(s.describe(), "no reading right now")
        finally:
            s.close()


class LaserSetup(unittest.TestCase):
    def make(self, readings, **kw):
        cfg = SensorConfig(enabled=True, tof=True, ultrasonic=False, **kw)
        return RangeSensor(cfg, sim=False, laser_factory=lambda c: FakeLaser(readings))

    def test_reads_millimetres_as_centimetres(self):
        s = self.make([1234])
        try:
            self.assertTrue(wait_for(lambda: s.distance_cm is not None))
            self.assertAlmostEqual(s.distance_cm, 123.4, places=1)
            self.assertTrue(s.available)
        finally:
            s.close()

    def test_far_readings_are_held_at_the_maximum(self):
        s = self.make([3000], max_cm=200)
        try:
            self.assertTrue(wait_for(lambda: s.distance_cm is not None))
            self.assertEqual(s.distance_cm, 200.0)
            self.assertIn("clear ahead", s.describe())
        finally:
            s.close()

    def test_rejected_readings_are_ignored(self):
        r = LaserReader(FakeLaser([-1, 0]))
        time.sleep(0.05)
        self.assertIsNone(r.distance_cm)
        r.close()

    def test_a_stuck_sensor_goes_stale_instead_of_holding_an_old_number(self):
        now = [0.0]
        dev = FakeLaser([500])
        r = LaserReader(dev, stale_s=0.6, clock=lambda: now[0])
        self.assertTrue(wait_for(lambda: r.distance_cm == 50.0))
        now[0] = 5.0                                   # time passes with no new reading
        r._at = 0.0
        self.assertIsNone(r.distance_cm)
        r.close()
        self.assertTrue(dev.stopped)

    def test_a_failing_bus_gives_no_reading_and_does_not_crash(self):
        class Broken:
            def get_distance(self):
                raise OSError("i2c")

            def stop_ranging(self):
                pass

        r = LaserReader(Broken())
        time.sleep(0.05)
        self.assertIsNone(r.distance_cm)
        r.close()

    def test_missing_library_leaves_the_other_sensor_working(self):
        def no_library(cfg):
            raise ImportError("No module named VL53L1X")

        cfg = SensorConfig(enabled=True, tof=True, ultrasonic=False)
        s = RangeSensor(cfg, sim=False, laser_factory=no_library)
        self.assertFalse(s.available)                  # and it started without raising
        s.close()


if __name__ == "__main__":
    unittest.main()
