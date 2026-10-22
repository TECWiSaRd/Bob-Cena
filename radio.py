"""Radio between two robots (Bob and John), over Bluetooth or Wi-Fi. Standard library only, so this
file can be copied into the other robot's code unchanged.

Transport "bluetooth": an RFCOMM serial link. One robot listens (role "listen"), the other
calls it (role "connect", given the listener's Bluetooth address). Pair the two Pis
first (see README) so the link is encrypted.

Transport "wifi": the same thing over TCP. The listener opens a port (default 8765); the caller
connects to it by host name or IP address (peer_address). Both robots must be able to reach
each other: the same Wi-Fi network, or a VPN such as Tailscale. The messages are signed but NOT
encrypted, so over the open internet use a VPN. Everything below is the same on both transports.

Protocol: one JSON object per line (UTF-8, "\\n" terminated):

    {"v":1, "id":"<8 hex>", "from":"Bob", "ts":1700000000, "type":"msg", "text":"hi", "sig":"<hex>"}

type is "hello" (sent once when linked), "msg" (a chat message) or "ping" (keep-alive).
sig = HMAC-SHA256(shared secret, "v|id|from|ts|type|text") as lowercase hex, where the
fields are joined with "|" in that order. Anything unsigned or wrongly signed is dropped,
so a stranger in Bluetooth range can't talk to the robot even if they connect.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import socket
import threading
import time
from collections import deque
from pathlib import Path

log = logging.getLogger("bob.radio")

PROTOCOL = 1
MAX_TEXT = 500
MAX_LINE = 4096
PING_EVERY = 10.0
DEAD_AFTER = 40.0
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,20}$")
SIGNED_FIELDS = ("v", "id", "from", "ts", "type", "text")
TRANSPORTS = ("bluetooth", "wifi")
HANDSHAKE_S = 10.0       # a new connection must send one valid message within this long, or it is dropped


def sign(secret: str, msg: dict) -> str:
    data = "|".join(str(msg[k]) for k in SIGNED_FIELDS)  # text is last, so a "|" inside it is unambiguous
    return hmac.new(secret.encode(), data.encode(), hashlib.sha256).hexdigest()


def make_message(secret: str, sender: str, type_: str, text: str = "", *, msg_id=None, ts=None) -> dict:
    msg = {"v": PROTOCOL, "id": msg_id or secrets.token_hex(4), "from": sender,
           "ts": int(time.time() if ts is None else ts), "type": type_, "text": text}
    msg["sig"] = sign(secret, msg)
    return msg


def verify(secret: str, msg) -> bool:
    if not isinstance(msg, dict) or not all(k in msg for k in SIGNED_FIELDS + ("sig",)):
        return False
    if msg["v"] != PROTOCOL or not all(isinstance(msg[k], str) for k in ("id", "from", "type", "text", "sig")):
        return False
    return hmac.compare_digest(sign(secret, msg), msg["sig"])


def clean_text(text: str) -> str:
    """One line of printable text. Newlines are removed so a message can't pose as a new
    section (for example 'Operator says:') in the robot's prompt."""
    text = "".join(ch if ch.isprintable() else " " for ch in str(text))
    return " ".join(text.split())[:MAX_TEXT]


class Radio(threading.Thread):
    def __init__(self, name, peer_name, secret, role, peer_address, channel, on_message,
                 ai_max_per_minute=6, log_path: Path | None = None,
                 transport="bluetooth", port=8765, bind="0.0.0.0"):
        super().__init__(name="radio", daemon=True)
        for n in (name, peer_name):
            if not NAME_RE.match(n):
                raise ValueError(f"robot names must be 1-20 letters, digits, - or _ (got {n!r})")
        if role not in ("listen", "connect"):
            raise ValueError('radio role must be "listen" or "connect"')
        if transport not in TRANSPORTS:
            raise ValueError(f'radio transport must be one of: {", ".join(TRANSPORTS)}')
        if role == "connect" and not peer_address:
            raise ValueError('role "connect" needs the other robot\'s address (peer_address): '
                             + ("its host name or IP address" if transport == "wifi" else "its Bluetooth address"))
        if transport == "wifi" and not 0 <= int(port) <= 65535:     # 0 = let the system choose (tests)
            raise ValueError("radio port must be 1-65535")
        self.transport, self.port, self.bind = transport, int(port), bind
        self.bound_port = 0              # the port actually listening (differs from `port` only when port is 0)
        self.name_, self.peer, self.secret, self.role = name, peer_name, secret, role
        self.peer_address, self.channel, self.on_message = peer_address, channel, on_message
        self.ai_max_per_minute, self.log_path = ai_max_per_minute, log_path
        if log_path:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        self.enabled = True
        self.state = "starting"          # starting | waiting | connecting | handshake | connected | off
        self.history: deque[dict] = deque(maxlen=200)
        self.sent = self.received = self.rejected = 0
        self._sock = None
        self._server = None
        self._send_lock = threading.Lock()
        self._ai_sent: deque[float] = deque()
        self._seen: deque[str] = deque(maxlen=300)
        self._in_times: deque[float] = deque()
        self._quit = threading.Event()
        self._last_error = ""

    # ---- transports (replaced in tests) -------------------------------------------
    def _open_server(self):
        if self.transport == "wifi":
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.bind, self.port))
            server.listen(1)
            self.bound_port = server.getsockname()[1]
            return server
        server = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        server.bind(("00:00:00:00:00:00", self.channel))
        server.listen(1)
        return server

    def _open_client(self):
        if self.transport == "wifi":
            sock = socket.create_connection((self.peer_address, self.port), timeout=10)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            return sock
        sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        sock.settimeout(10)
        try:
            sock.connect((self.peer_address, self.channel))
        except Exception:
            sock.close()
            raise
        return sock

    # ---- operator controls -------------------------------------------------------
    @property
    def connected(self) -> bool:
        return self.state == "connected"

    def set_enabled(self, on: bool) -> str:
        self.enabled = on
        if not on:
            self._drop()
            self.state = "off"
        return f"radio {'on' if on else 'off'}"

    def where(self) -> str:
        if self.transport == "wifi":
            return f"Wi-Fi{', ' + self.peer_address if self.peer_address else ''}, port {self.bound_port or self.port}"
        return f"Bluetooth{', ' + self.peer_address if self.peer_address else ''}, channel {self.channel}"

    def status(self) -> str:
        return (f"radio {self.state}: {self.name_} <-> {self.peer} ({self.role}, {self.where()}); "
                f"sent {self.sent}, received {self.received}, rejected {self.rejected}"
                + (f"; last problem: {self._last_error}" if self._last_error and not self.connected else ""))

    def format_history(self, n: int = 15) -> list[str]:
        out = []
        for h in list(self.history)[-n:]:
            arrow = f"{h['from']} -> {h['to']}"
            out.append(f"{time.strftime('%H:%M:%S', time.localtime(h['ts']))} {arrow}: {h['text']}")
        return out

    def stop(self) -> None:
        self._quit.set()
        self.enabled = False
        self._drop()
        if self._server:
            try:
                self._server.close()
            except OSError:
                pass

    # ---- sending -----------------------------------------------------------------
    def send(self, text: str, source: str = "ai") -> tuple[bool, str]:
        text = clean_text(text)
        if not text:
            return False, "empty message"
        if not self.connected:
            return False, f"{self.peer} is not connected right now"
        now = time.monotonic()
        if source == "ai":
            while self._ai_sent and now - self._ai_sent[0] > 60:
                self._ai_sent.popleft()
            if len(self._ai_sent) >= self.ai_max_per_minute:
                return False, (f"radio rate limit: at most {self.ai_max_per_minute} messages a minute "
                               "- wait a bit, and keep messages short")
        try:
            self._send_raw(make_message(self.secret, self.name_, "msg", text))
        except OSError as e:
            self._drop()
            return False, f"radio send failed ({e})"
        if source == "ai":
            self._ai_sent.append(now)
        self.sent += 1
        self._record(self.name_, self.peer, text)
        return True, f"sent to {self.peer}"

    def _send_raw(self, msg: dict) -> None:
        data = (json.dumps(msg, separators=(",", ":")) + "\n").encode()
        with self._send_lock:
            sock = self._sock
            if sock is None:
                raise OSError("not connected")
            sock.sendall(data)

    def _record(self, sender: str, to: str, text: str) -> None:
        entry = {"ts": time.time(), "from": sender, "to": to, "text": text}
        self.history.append(entry)
        log.info("RADIO %s -> %s: %s", sender, to, text)
        if self.log_path:
            try:
                with open(self.log_path, "a") as f:
                    f.write(json.dumps(entry) + "\n")
            except OSError:
                pass

    # ---- connection loop ---------------------------------------------------------
    def _drop(self) -> None:
        sock, self._sock = self._sock, None
        if sock:
            try:
                sock.close()
            except OSError:
                pass

    def run(self) -> None:
        while not self._quit.is_set():
            if not self.enabled:
                self._quit.wait(0.5)
                continue
            try:
                sock = self._accept() if self.role == "listen" else self._dial()
            except Exception as e:
                self._problem(e)
                self._quit.wait(5)
                continue
            if sock is not None:
                self._session(sock)

    def _problem(self, e: Exception) -> None:
        msg = str(e) or type(e).__name__
        if msg != self._last_error:  # don't repeat the same complaint every few seconds
            log.warning("Radio: %s", msg)
        self._last_error = msg

    def _accept(self):
        self.state = "waiting"
        if self._server is None:
            self._server = self._open_server()
            self._server.settimeout(1.0)
            log.info("Radio: waiting for %s on %s", self.peer, self.where())
        try:
            sock, addr = self._server.accept()
        except (socket.timeout, TimeoutError):
            return None
        log.info("Radio: incoming connection from %s", addr[0] if isinstance(addr, tuple) else addr)
        return sock

    def _dial(self):
        self.state = "connecting"
        return self._open_client()

    def _session(self, sock) -> None:
        sock.settimeout(1.0)
        self._sock = sock
        self.state = "handshake"
        buf = b""
        started = last_heard = last_ping = time.monotonic()
        try:
            self._send_raw(make_message(self.secret, self.name_, "hello"))
            while not self._quit.is_set() and self.enabled and self._sock is sock:
                now = time.monotonic()
                if now - last_ping >= PING_EVERY:
                    self._send_raw(make_message(self.secret, self.name_, "ping"))
                    last_ping = now
                if now - last_heard > DEAD_AFTER:
                    raise OSError("no signal from the other robot")
                if not self.connected and now - started > HANDSHAKE_S:
                    raise OSError("no valid hello from whoever connected")     # a stranger can't hold the only slot
                try:
                    chunk = sock.recv(1024)
                except (socket.timeout, TimeoutError):
                    continue
                if not chunk:
                    raise OSError("the other robot hung up")
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if self._handle(line):
                        last_heard = time.monotonic()
                if len(buf) > MAX_LINE:
                    buf = b""
                    self.rejected += 1
        except OSError as e:
            if self.enabled and not self._quit.is_set():
                log.info("Radio: link to %s lost (%s)", self.peer, e)
        finally:
            if self._sock is sock:
                self._drop()
            else:
                try:
                    sock.close()
                except OSError:
                    pass
            self.state = "off" if not self.enabled else ("waiting" if self.role == "listen" else "connecting")
            if self.role == "connect":
                self._quit.wait(3)

    def _handle(self, line: bytes) -> bool:
        """Process one received line. Returns True if it was a valid message from our peer."""
        if len(line) > MAX_LINE:
            self.rejected += 1
            return False
        try:
            msg = json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self.rejected += 1
            return False
        if not verify(self.secret, msg) or msg["from"] != self.peer:
            self.rejected += 1
            if self.rejected <= 3 or self.rejected % 25 == 0:  # an attacker shouldn't be able to flood the log
                log.warning("Radio: dropped a message that failed authentication (%d so far)", self.rejected)
            return False
        if msg["id"] in self._seen:
            return True  # duplicate (a replay); ignore silently
        self._seen.append(msg["id"])
        if msg["type"] == "hello":
            if not self.connected:
                self.state = "connected"
                log.info("Radio: linked with %s", self.peer)
        elif msg["type"] == "msg":
            now = time.monotonic()
            while self._in_times and now - self._in_times[0] > 60:
                self._in_times.popleft()
            if len(self._in_times) >= 30:  # a runaway peer must not flood the robot's prompt
                self.rejected += 1
                return True
            self._in_times.append(now)
            text = clean_text(msg["text"])
            if text:
                self.received += 1
                self._record(self.peer, self.name_, text)
                try:
                    self.on_message(self.peer, text)
                except Exception:
                    log.exception("Radio message handler failed")
        return True
