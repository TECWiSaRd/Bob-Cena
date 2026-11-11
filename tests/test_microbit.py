import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import microbit  # noqa: E402
from microbit import MicroBit, parse  # noqa: E402


class FakeCtrl:
    def __init__(self):
        self.drive_mode = False
        self.moves, self.stops, self.estops, self.handled, self.talks = [], 0, [], [], 0
        self.drive = SimpleNamespace(stop=self._stop, estop=threading.Event())
        self.listener = SimpleNamespace(ptt_toggle=self._talk)

    def _stop(self):
        self.stops += 1

    def driving_for(self, who):
        return self.drive_mode and who == "microbit"

    def leave_drive(self, who):
        if who == "microbit":
            self.drive_mode = False

    def _talk(self):
        self.talks += 1
        return "talking"

    def manual(self, l, r, s):
        self.moves.append((round(l, 2), round(r, 2), s))

    def estop(self, source):
        self.estops.append(source)
        self.drive_mode = False
        self.drive.estop.set()

    def handle(self, line, **k):
        self.handled.append(line)
        if line == "/drive":
            self.drive_mode = True
        if line == "/clear":
            self.drive.estop.clear()
        return "ok"


class Clock:
    t = 100.0

    def __call__(self):
        return self.t


class FakePort:
    def __init__(self, chunks=()):
        self.chunks, self.written, self.closed = list(chunks), [], False

    def read(self, n):
        if not self.chunks:
            raise OSError("unplugged")
        return self.chunks.pop(0)

    def write(self, data):
        self.written.append(data.decode())

    def close(self):
        self.closed = True


def make(**cfg):
    c = config.MicrobitConfig(enabled=True, **cfg)
    ctrl, clock = FakeCtrl(), Clock()
    return MicroBit(c, ctrl, clock=clock), ctrl, clock


class ParseTests(unittest.TestCase):
    def test_lines_are_understood(self):
        self.assertEqual(parse("D 50 -100\n"), ("D", (0.5, -1.0), ""))
        self.assertEqual(parse("d 500 -900 k7"), ("D", (1.0, -1.0), "k7"))   # clamped, case-insensitive
        self.assertEqual(parse("M"), ("M", (), ""))
        self.assertEqual(parse("E"), ("E", (), ""))
        self.assertEqual(parse("T word"), ("T", (), "word"))

    def test_rubbish_is_ignored(self):
        for bad in ["", "   ", "D", "D 1", "D a b", "D nan 1", "X 1 2", "D " + "1 " * 40, "\x00\xff"]:
            self.assertIsNone(parse(bad), bad)


class DrivingTests(unittest.TestCase):
    def drive_on(self, mb, ctrl):
        mb.line("M")
        self.assertTrue(ctrl.drive_mode)

    def test_tilt_does_nothing_until_manual_drive_is_on(self):
        mb, ctrl, _ = make()
        mb.line("D 100 100")
        self.assertEqual(ctrl.moves, [])
        self.drive_on(mb, ctrl)
        mb.line("D 0 100")
        self.assertEqual(ctrl.moves, [(0.6, 0.6, microbit.PULSE_S)])

    def test_turning_and_deadzone_and_the_speed_fraction(self):
        mb, ctrl, _ = make(speed=1.0)
        self.drive_on(mb, ctrl)
        mb.line("D 100 0")                       # turn right on the spot
        mb.line("D 10 10")                       # inside the dead zone
        mb.line("D 100 100")                     # forward and right: scaled so neither wheel is over 1
        self.assertEqual(ctrl.moves, [(1.0, -1.0, 0.4), (1.0, 0.0, 0.4)])

    def test_letting_go_stops_and_so_does_silence(self):
        mb, ctrl, clock = make()
        self.drive_on(mb, ctrl)
        mb.line("D 0 100")
        mb.line("D 0 0")
        self.assertEqual(ctrl.stops, 1)
        mb.line("D 0 100")
        clock.t += 1.0                           # nothing more arrives
        mb.tick()
        self.assertEqual(ctrl.stops, 2)
        mb.tick()
        self.assertEqual(ctrl.stops, 2)

    def test_b_toggles_manual_drive(self):
        mb, ctrl, _ = make()
        mb.line("M")
        self.assertEqual(ctrl.handled, ["/drive"])
        mb.line("M")
        self.assertFalse(ctrl.drive_mode)
        self.assertEqual(ctrl.stops, 1)

    def test_drive_can_be_switched_off_entirely(self):
        mb, ctrl, _ = make(drive=False)
        mb.line("M")
        self.assertEqual(ctrl.handled, [])
        mb.line("E")
        self.assertEqual(ctrl.estops, ["micro:bit"])

    def test_nothing_moves_during_an_emergency_stop(self):
        mb, ctrl, _ = make()
        self.drive_on(mb, ctrl)
        mb.line("E")
        mb.line("D 0 100")
        self.assertEqual(ctrl.moves, [])
        self.assertEqual(mb.mode(), "estop")


class SafetyTests(unittest.TestCase):
    def test_estop_needs_no_key_but_everything_else_does(self):
        mb, ctrl, _ = make(key="sesame")
        mb.line("M")                             # no key
        mb.line("M wrong")
        self.assertEqual(ctrl.handled, [])
        mb.line("T")
        self.assertEqual(ctrl.talks, 0)
        mb.line("M sesame")
        self.assertEqual(ctrl.handled, ["/drive"])
        mb.line("E")                             # a stop is always welcome
        self.assertEqual(ctrl.estops, ["micro:bit"])

    def test_releasing_the_estop_is_off_unless_allowed(self):
        mb, ctrl, _ = make()
        mb.line("E")
        mb.line("C")
        self.assertTrue(ctrl.drive.estop.is_set())
        mb2, ctrl2, _ = make(allow_clear=True)
        mb2.line("E")
        mb2.line("C")
        self.assertFalse(ctrl2.drive.estop.is_set())

    def test_a_clear_needs_the_key_too(self):
        mb, ctrl, _ = make(key="k", allow_clear=True)
        mb.line("E")
        mb.line("C")
        self.assertTrue(ctrl.drive.estop.is_set())
        mb.line("C k")
        self.assertFalse(ctrl.drive.estop.is_set())

    def test_claude_has_no_way_to_use_it(self):
        import brain
        src = Path(brain.__file__).read_text().lower()
        self.assertNotIn("microbit", src)


class PortTests(unittest.TestCase):
    def test_lines_split_across_reads_and_junk_is_dropped(self):
        mb, ctrl, _ = make()
        port = FakePort([b"M\nD 0 1", b"00\nzzz\n"])
        buf = bytearray()
        self.assertTrue(mb._read(port, buf))
        self.assertTrue(ctrl.drive_mode)
        self.assertTrue(mb._read(port, buf))
        self.assertEqual(ctrl.moves, [(0.6, 0.6, 0.4)])
        self.assertFalse(mb._read(port, buf))      # unplugged

    def test_a_long_line_without_a_newline_is_thrown_away(self):
        mb, ctrl, _ = make()
        buf = bytearray()
        mb._read(FakePort([b"x" * 1000]), buf)
        self.assertEqual(len(buf), 0)

    def test_bob_tells_the_micro_bit_what_he_is_doing(self):
        mb, ctrl, _ = make()
        port = FakePort()
        mb._port = port
        mb.line("M")
        mb.line("E")
        mb.line("E")                               # no repeat of the same news
        self.assertEqual(port.written, ["MODE drive\n", "MODE estop\n"])

    def test_unplugging_stops_the_wheels(self):
        mb, ctrl, _ = make()
        mb.line("M")
        mb.line("D 0 100")
        mb.lost()
        self.assertEqual(ctrl.stops, 1)

    def test_the_thread_finds_a_port_reads_it_and_stops_when_it_goes(self):
        ports = [FakePort([b"M\n", b"D 0 100\n"])]
        ctrl, clock = FakeCtrl(), Clock()
        mb = MicroBit(config.MicrobitConfig(enabled=True), ctrl, find=lambda: ["/dev/serial/by-id/usb-micro:bit"],
                      opener=lambda path: ports.pop(0) if ports else (_ for _ in ()).throw(OSError("gone")), clock=clock)
        mb.halt.wait = lambda t=None: mb.halt.set()      # don't sleep in the test
        mb.run()
        self.assertEqual(ctrl.moves, [(0.6, 0.6, 0.4)])
        self.assertGreaterEqual(ctrl.stops, 1)
        self.assertEqual(mb.connected, "")

    def test_find_devices_matches_only_micro_bits(self):
        import os
        real = os.listdir
        os.listdir = lambda p: ["usb-ARM_BBC_micro:bit_CMSIS-DAP_123-if01", "usb-FTDI_cable"]
        try:
            self.assertEqual(microbit.find_devices(), ["/dev/serial/by-id/usb-ARM_BBC_micro:bit_CMSIS-DAP_123-if01"])
        finally:
            os.listdir = real


class FakeBleak:
    """A pretend bleak: one micro:bit that can be found, connected to, written to, and made to talk or vanish."""

    def __init__(self, devices=(("BBC micro:bit [tupaz]", "AA:BB:CC:DD:EE:01"),)):
        outer = self
        self.devices, self.written, self.notify, self.connected = list(devices), [], None, False
        self.disconnected = None

        class Scanner:
            @staticmethod
            async def find_device_by_filter(match, timeout=None):
                for name, addr in outer.devices:
                    dev = SimpleNamespace(name=name, address=addr)
                    if match(dev, SimpleNamespace(local_name=name)):
                        return dev
                return None

        class Client:
            def __init__(self, dev, disconnected_callback=None):
                outer.disconnected = disconnected_callback
                self.dev = dev

            async def connect(self):
                outer.connected = True

            async def start_notify(self, uuid, cb):
                assert uuid == microbit.UART_TX
                outer.notify = cb

            async def write_gatt_char(self, uuid, data, response=True):
                assert uuid == microbit.UART_RX and response is False
                outer.written.append(bytes(data))

            async def disconnect(self):
                outer.connected = False

        self.BleakScanner, self.BleakClient = Scanner, Client


class BluetoothTests(unittest.TestCase):
    def link(self, fake, **kw):
        return microbit.BleLink(bleak=fake, **kw)

    def test_finds_connects_reads_and_writes(self):
        fake = FakeBleak()
        link = self.link(fake, name="tupaz").open()
        try:
            self.assertTrue(fake.connected)
            fake.notify(None, bytearray(b"M\n"))
            self.assertEqual(link.read(256), b"M\n")
            self.assertEqual(link.read(256), b"")
            link.write(b"MODE drive\n")
            self.assertEqual(fake.written, [b"MODE drive\n"])
        finally:
            link.close()
        self.assertFalse(fake.connected)

    def test_the_name_must_match_and_an_address_wins(self):
        fake = FakeBleak([("BBC micro:bit [other]", "AA:BB:CC:DD:EE:02"), ("Some speaker", "AA:BB:CC:DD:EE:03")])
        with self.assertRaises(OSError):
            self.link(fake, name="tupaz").open()
        link = self.link(fake, address="aa:bb:cc:dd:ee:02").open()    # case does not matter
        link.close()
        self.assertTrue(self.link(FakeBleak(), name="").matches("BBC micro:bit [x]", None))
        self.assertFalse(self.link(FakeBleak(), name="").matches("Some speaker", None))

    def test_losing_the_link_is_an_error_for_the_reader(self):
        fake = FakeBleak()
        link = self.link(fake).open()
        try:
            fake.disconnected(None)
            with self.assertRaises(OSError):
                link.read(256)
            with self.assertRaises(OSError):
                link.write(b"x")
        finally:
            link.close()

    def test_the_whole_thread_over_bluetooth_and_the_wheels_stop_when_it_drops(self):
        fake = FakeBleak()
        ctrl = FakeCtrl()
        cfg = config.MicrobitConfig(enabled=True, transport="ble", ble_name="tupaz")
        mb = MicroBit(cfg, ctrl)
        real = microbit.BleLink
        microbit.BleLink = lambda n, a: real(n, a, bleak=fake)
        try:
            attempts = []
            orig_open = mb._open

            def opener(path):
                attempts.append(path)
                if len(attempts) > 1:
                    mb.halt.set()
                    raise OSError("stop")
                link = orig_open(path)
                fake.notify(None, bytearray(b"M\n"))
                fake.notify(None, bytearray(b"D 0 100\n"))
                threading.Timer(0.3, lambda: fake.disconnected(None)).start()
                return link

            mb._open = opener
            mb.halt.wait = lambda t=None: None
            mb.run()
        finally:
            microbit.BleLink = real
        self.assertEqual(attempts[0], "bluetooth")
        self.assertEqual(ctrl.moves, [(0.6, 0.6, 0.4)])
        self.assertIn("MODE drive\n", [w.decode() for w in fake.written])
        self.assertGreaterEqual(ctrl.stops, 1)

    def test_an_unknown_transport_is_refused(self):
        with self.assertRaises(ValueError):
            MicroBit(config.MicrobitConfig(enabled=True, transport="smoke"), FakeCtrl())


class ConfigTests(unittest.TestCase):
    def test_shipped_config_is_off_and_safe(self):
        cfg = config.load(Path(__file__).resolve().parent.parent / "config.toml")
        self.assertFalse(cfg.microbit.enabled)
        self.assertFalse(cfg.microbit.allow_clear)


if __name__ == "__main__":
    unittest.main()
