"""The Bluetooth LE message format shared by Bob and the Bob app (the app has the same maths in app/lib/src/ble_codec.dart).

Messages are text lines ending in a newline, cut into small pieces for the radio and put back together on the other side. The app writes to
RX and Bob answers on TX. Every message that does something is signed, so nobody nearby can drive Bob without the key the app was given when it
was paired over the network:

    H <dev>                          hello: Bob answers N <nonce>
    D <dev> <ctr> <l> <r> <mac>      a drive pulse (0.4 s): wheel speeds -1..1
    S <dev> <ctr> <mac>              stop
    T <dev> <ctr> <mac>              status
    C <dev> <ctr> <mac> <text>       a console command (the same list the app may use over Wi-Fi)
    E                                emergency stop (accepted from anyone nearby unless [ble] open_estop is off)

<dev> is the first 8 hex digits of sha256 of the device's name. <ctr> counts up from 1 for each <nonce>, which Bob makes up for each hello, so
a recorded message can never be replayed. <mac> is the first 16 hex digits of HMAC-SHA256 with the device's key over
"<dev>|<nonce>|<ctr>|<what was sent>" where <what was sent> is "D <l> <r>", "S", "T" or "C <text>" exactly as written.
"""
from __future__ import annotations

import hashlib
import hmac
import time

SERVICE = "b0b10001-ce17-4c0b-a000-b0b0b0b0b0b0"
RX = "b0b10002-ce17-4c0b-a000-b0b0b0b0b0b0"      # the app writes here
TX = "b0b10003-ce17-4c0b-a000-b0b0b0b0b0b0"      # Bob notifies here
CHUNK = 20                                       # bytes per radio packet: fits the smallest Bluetooth packet size
MAX_LINE = 400


def short_id(device: str) -> str:
    """The 8 hex digits that stand for a device's name in every message."""
    return hashlib.sha256(device.encode()).hexdigest()[:8]


def mac(key_hex: str, dev: str, nonce: str, ctr: int, body: str) -> str:
    """The signature of one message."""
    msg = f"{dev}|{nonce}|{ctr}|{body}".encode()
    return hmac.new(bytes.fromhex(key_hex), msg, hashlib.sha256).hexdigest()[:16]


def chunks(text: str, size: int = CHUNK) -> list[bytes]:
    """A line (a newline is added) cut into packets."""
    data = (text.rstrip("\n") + "\n").encode()
    return [data[i:i + size] for i in range(0, len(data), size)]


class LineAssembler:
    """Puts packets back together into lines. A half-finished line that never ends is dropped after a few seconds, and a line that grows
    too long is thrown away, so garbage can't pile up."""

    def __init__(self, limit: int = MAX_LINE, stale_s: float = 3.0, clock=time.monotonic):
        self.limit, self.stale_s, self._clock = limit, stale_s, clock
        self._buf = b""
        self._last = 0.0
        self._skip = False                  # inside a line that was too long: ignore up to its newline

    def feed(self, data: bytes) -> list[str]:
        now = self._clock()
        if self._buf and now - self._last > self.stale_s:
            self._buf = b""
        self._last = now
        lines = []
        for byte in bytes(data):
            if byte == 10:                  # newline
                if not self._skip and self._buf:
                    lines.append(self._buf.decode("utf-8", "replace").strip())
                self._buf, self._skip = b"", False
            elif not self._skip:
                self._buf += bytes([byte])
                if len(self._buf) > self.limit:
                    self._buf, self._skip = b"", True
        return [line for line in lines if line]
