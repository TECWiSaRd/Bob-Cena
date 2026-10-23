"""What the Bob app talks to: pairing, paired devices, and the version-1 API's building blocks.

Pairing: you type /pair in Bob's console, which shows a one-time code (12 characters, good for 5 minutes). In the app you
enter the code. The code itself is NEVER sent over the network. Instead each side proves it knows it:

    app  -> Bob:  device name, a random nonce, and  HMAC(code, "pair-client|" + nonce + "|" + fingerprint the app saw)
    Bob  -> app:  a device token, and  HMAC(code, "pair-server|" + nonce + "|" + Bob's fingerprint + "|" + token)

The fingerprint is that of the HTTPS certificate. Somebody sitting in the middle presents a different certificate, so the
fingerprints differ and the proof fails; and they cannot work out the code from the proof (12 characters is about 59 bits).
The app then pins the fingerprint and uses the token (kept here only as a hash) on every request.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path

log = logging.getLogger("bob.appapi")

ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"        # no 0/O, 1/I/L: easy to read and type
CODE_LENGTH = 12
CODE_LIFETIME = 300.0
MAX_WRONG_PER_CODE = 8
MAX_DEVICES = 20


def normalize_code(text: str) -> str:
    return "".join(c for c in str(text).upper() if c.isalnum())


def show_code(code: str) -> str:
    return "-".join(code[i:i + 4] for i in range(0, len(code), 4))


def _hmac(code: str, message: str) -> str:
    return hmac.new(code.encode(), message.encode(), hashlib.sha256).hexdigest()


def client_proof(code: str, nonce: str, fingerprint: str) -> str:
    return _hmac(normalize_code(code), f"pair-client|{nonce}|{fingerprint}")


def server_proof(code: str, nonce: str, fingerprint: str, token: str) -> str:
    return _hmac(normalize_code(code), f"pair-server|{nonce}|{fingerprint}|{token}")


class DeviceStore:
    """Paired devices. Only a hash of each token is kept, so reading the file doesn't let you act as a device."""

    def __init__(self, path: Path | None, clock=time.time):
        self.path, self._clock = (Path(path) if path else None), clock          # no path = kept in memory only (tests)
        self._lock = threading.Lock()
        self.devices: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.path is None:
            return
        try:
            data = json.loads(self.path.read_text())
            self.devices = {str(k): dict(v) for k, v in data["devices"].items()}
        except FileNotFoundError:
            return
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            bad = self.path.with_name(self.path.name + ".bad")
            try:
                os.replace(self.path, bad)
            except OSError:
                pass
            log.warning("devices.json was unreadable (%s): kept as %s; every device has to pair again", e, bad.name)

    def _save(self) -> None:
        if self.path is None:
            return
        tmp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"devices": self.devices}, f, indent=1)
        os.replace(tmp, self.path)

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def add(self, name: str, by: str = "") -> tuple[str, str]:
        """(device id, token). The token is shown once and never stored."""
        name = " ".join(str(name).split())[:40] or "device"
        with self._lock:
            if len(self.devices) >= MAX_DEVICES:
                raise ValueError(f"{MAX_DEVICES} devices are paired already; remove one first (/devices remove NAME)")
            base, n, ident = name, 2, name
            while ident in self.devices:
                ident, n = f"{base} ({n})", n + 1
            token = secrets.token_urlsafe(32)
            self.devices[ident] = {"token_hash": self._hash(token), "created": self._clock(), "last_seen": None, "by": by}
            self._save()
            return ident, token

    def check(self, token: str) -> str | None:
        """The device this token belongs to, or None. Compares against every device so timing reveals nothing."""
        if not token:
            return None
        given = self._hash(token)
        found = None
        with self._lock:
            for ident, info in self.devices.items():
                if hmac.compare_digest(given, info.get("token_hash", "")) and found is None:
                    found = ident
            if found:
                now = self._clock()
                if now - (self.devices[found].get("last_seen") or 0) > 60:          # not a disk write on every request
                    self.devices[found]["last_seen"] = now
                    try:
                        self._save()
                    except OSError:
                        pass
        return found

    def remove(self, name: str) -> bool:
        with self._lock:
            hit = next((k for k in self.devices if k.lower() == name.lower()), None)
            if hit is None:
                return False
            del self.devices[hit]
            self._save()
            return True

    def describe(self) -> list[str]:
        out = []
        with self._lock:
            for ident, info in sorted(self.devices.items()):
                seen = info.get("last_seen")
                ago = "never used" if not seen else f"last used {max(0, int((self._clock() - seen) / 60))} min ago"
                out.append(f"{ident} (paired by {info.get('by') or '?'}, {ago})")
        return out


class Pairing:
    def __init__(self, devices: DeviceStore, fingerprint: str, robot: str = "Bob", clock=time.monotonic):
        self.devices, self.fingerprint, self.robot, self._clock = devices, fingerprint, robot, clock
        self._codes: dict[str, dict] = {}              # code -> {"expires", "by", "wrong"}
        self._lock = threading.Lock()

    def new_code(self, by: str) -> str:
        code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
        with self._lock:
            self._purge()
            if len(self._codes) >= 3:                           # a few at a time is plenty
                oldest = min(self._codes, key=lambda c: self._codes[c]["expires"])
                del self._codes[oldest]
            self._codes[code] = {"expires": self._clock() + CODE_LIFETIME, "by": by, "wrong": 0}
        return code

    def _purge(self) -> None:
        now = self._clock()
        for c in [c for c, v in self._codes.items() if v["expires"] < now or v["wrong"] >= MAX_WRONG_PER_CODE]:
            del self._codes[c]

    def open_codes(self) -> int:
        with self._lock:
            self._purge()
            return len(self._codes)

    def redeem(self, device: str, nonce: str, proof: str) -> dict | None:
        """The reply for the app, or None when the proof doesn't match any open code."""
        if not (isinstance(nonce, str) and 8 <= len(nonce) <= 64 and isinstance(proof, str)):
            return None
        with self._lock:
            self._purge()
            match = None
            for code, info in self._codes.items():
                if hmac.compare_digest(client_proof(code, nonce, self.fingerprint), proof) and match is None:
                    match = code
            if match is None:
                for info in self._codes.values():
                    info["wrong"] += 1
                return None
            by = self._codes.pop(match)["by"]               # single use
        ident, token = self.devices.add(device, by)
        log.info("Device paired: %s (code from %s)", ident, by)
        return {"token": token, "device": ident, "name": self.robot, "fingerprint": self.fingerprint,
                "server_proof": server_proof(match, nonce, self.fingerprint, token)}


# ---- the version-1 HTTP API (called from stream.py's request handler) -------------------------------------------------
API_VERSION = 1
MAX_BODY = 4096


def _read_json(h) -> dict | None:
    """The JSON object in the request body, or None after sending an error reply."""
    if "application/json" not in h.headers.get("Content-Type", ""):
        h._json({"error": "JSON only"}, 415)
        return None
    try:
        n = int(h.headers.get("Content-Length", ""))
    except ValueError:
        h.close_connection = True
        h._json({"error": "Content-Length required"}, 411)
        return None
    if n < 0 or n > MAX_BODY:
        h.close_connection = True
        h._json({"error": "bad request size"}, 413 if n > MAX_BODY else 400)
        return None
    try:
        body = json.loads(h.rfile.read(n) or b"{}")
        if not isinstance(body, dict):
            raise ValueError("not an object")
        return body
    except (ValueError, TypeError):
        h._json({"error": "bad request"}, 400)
        return None


def _bearer(h) -> str:
    value = h.headers.get("Authorization", "")
    return value[7:].strip() if value[:7].lower() == "bearer " else ""


def authenticate(h, server) -> str | None:
    """Who is calling: a paired device, or a person with one of the older dashboard tokens. None after a 401."""
    ip = h.client_address[0]
    if server.lockout.blocked(ip):
        h.close_connection = True
        h._json({"error": "too many wrong tries: wait a minute"}, 429)
        return None
    token = _bearer(h)
    who = server.devices.check(token) if token else None
    if who is None and token:
        who = server.policy.check(token, strong=True)
    if who is None:
        server.lockout.failed(ip)
        h._json({"error": "unauthorized"}, 401)
        return None
    server.note_user(who)
    return who


def handle_v1(h, server, method: str, url, query) -> None:
    """Route one /api/v1/... request."""
    path = url.path[len("/api/v1"):].rstrip("/") or "/"
    if not h.is_tls:
        return h._json({"error": "the app API only works over https (port %d)" % server.cfg.https_port}, 403)
    c = server.controller
    if path == "/info" and method == "GET":
        return h._json({"api": API_VERSION, "name": getattr(c.cfg.radio, "name", "Bob") if c else "Bob",
                        "version": server.version, "fingerprint": server.fingerprint})
    if path == "/pair" and method == "POST":
        ip = h.client_address[0]
        if server.lockout.blocked(ip):
            h.close_connection = True
            return h._json({"error": "too many wrong tries: wait a minute"}, 429)
        body = _read_json(h)
        if body is None:
            return
        reply = server.pairing.redeem(str(body.get("device", "device")), body.get("nonce"), body.get("proof"))
        if reply is None:
            server.lockout.failed(ip)
            return h._json({"error": "that code didn't work (wrong, expired or already used)"}, 401)
        return h._json(reply)
    if c is None:
        return h._json({"error": "Bob is still starting"}, 503)
    who = authenticate(h, server)
    if who is None:
        return
    if path == "/status" and method == "GET":
        return h._json(server.status())
    if path == "/cmd" and method == "POST":
        body = _read_json(h)
        if body is not None:
            h._json({"output": server.run_command(body.get("cmd", ""), by=f"app:{who}")})
        return
    if path == "/drive" and method == "POST":
        body = _read_json(h)
        if body is None:
            return
        try:
            left = max(-1.0, min(1.0, float(body.get("left", 0))))
            right = max(-1.0, min(1.0, float(body.get("right", 0))))
        except (ValueError, TypeError):
            return h._json({"error": "bad request"}, 400)
        if left != left or right != right:                                  # NaN
            return h._json({"error": "bad request"}, 400)
        if left == 0 and right == 0:
            c.drive.stop()
            return h._json({"output": ""})
        return h._json({"output": c.manual(left, right, 0.4)})
    if path == "/snapshot" and method == "GET":
        frame = server.hub.get()
        if frame is None:
            return h._send(503, b"camera off or unavailable", "text/plain")
        return h._send(200, frame, "image/jpeg")
    if path == "/stream" and method == "GET":
        return h._stream(still_ok=lambda: who in server.devices.devices or server.policy.check(_bearer(h), strong=True) is not None)
    if path == "/unpair" and method == "POST":
        removed = server.devices.remove(who) if who in server.devices.devices else False
        return h._json({"removed": removed})
    h._json({"error": "not found"}, 404)
