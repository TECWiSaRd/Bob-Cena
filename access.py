"""Who may use the camera page and the phone dashboard, and from which Wi-Fi network.

Several people can have their own token. Each token is tied to a Wi-Fi network, and it only works while Bob is
connected to that network. So a token given to a friend for their house works at their house and nowhere else,
and tokens for other houses stay dead until Bob is taken there. The owner's token (BOB_STREAM_TOKEN) works
everywhere.

In `.env`:

    BOB_STREAM_TOKEN=your-own-long-secret          # the owner: works on every network
    TOKEN_KAI=a-long-secret-for-kai                # one line per person; the name after TOKEN_ is their name
    TOKEN_SAM=a-long-secret-for-sam
    WIFI[Kai's House]=KAI                          # while Bob is on that Wi-Fi, Kai's token works
    WIFI[Sam Home]=SAM

This limits where a token is valid. It is not a replacement for the token: the network name isn't secret, so
the token is still what proves who you are. Bob reads the network name from his own Wi-Fi connection.
"""
from __future__ import annotations

import hmac
import logging
import re
import subprocess
import threading
import time
from pathlib import Path

log = logging.getLogger("bob.access")

TOKEN_LINE = re.compile(r"^TOKEN_([A-Za-z0-9_]+)\s*=\s*(.*)$")
WIFI_LINE = re.compile(r"^WIFI\[(.+)\]\s*=\s*([A-Za-z0-9_]+)\s*$")
MIN_LENGTH = 8
OWNER = "owner"


def _unquote(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1]
    return text


def parse_env(text: str) -> tuple[dict[str, str], dict[str, list[str]], list[str]]:
    """(tokens by lower-case name, names allowed on each network name, problems found)."""
    tokens: dict[str, str] = {}
    wifi: dict[str, list[str]] = {}
    problems: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = TOKEN_LINE.match(line)
        if m:
            name, secret = m.group(1).lower(), _unquote(m.group(2))
            if len(secret) < MIN_LENGTH:
                problems.append(f"TOKEN_{m.group(1)} is shorter than {MIN_LENGTH} characters, so it is ignored")
            else:
                tokens[name] = secret
            continue
        m = WIFI_LINE.match(line)
        if m:
            wifi.setdefault(_unquote(m.group(1)), []).append(m.group(2).lower())
    for ssid, names in list(wifi.items()):
        for name in names:
            if name not in tokens:
                problems.append(f"WIFI[{ssid}] points at {name.upper()}, but there is no usable TOKEN_{name.upper()}")
        wifi[ssid] = [n for n in names if n in tokens]
    return tokens, wifi, problems


def _run(args: list[str], timeout: float = 2.0) -> str | None:
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def current_wifi(run=_run) -> str | None:
    """The name of the Wi-Fi network Bob is connected to, or None (wired, or can't tell)."""
    out = run(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"])
    if out:
        for line in out.splitlines():
            if line.startswith("yes:"):
                return re.sub(r"\\(.)", r"\1", line[4:]) or None      # nmcli escapes ':' and '\\' with a backslash
    out = run(["iwgetid", "-r"])
    return out.strip() or None if out else None


class AccessPolicy:
    def __init__(self, owner_token: str = "", tokens: dict[str, str] | None = None,
                 wifi: dict[str, list[str]] | None = None, wifi_reader=current_wifi, clock=time.monotonic,
                 problems: list[str] | None = None, background: bool = True):
        self.owner_token = owner_token
        self.tokens = dict(tokens or {})
        self.wifi_map = dict(wifi or {})
        self.problems = list(problems or [])
        self._reader, self._clock = wifi_reader, clock
        self._cache: tuple[float, str | None] = (-1e9, None)
        self._lock = threading.Lock()
        self._background = background
        self._refreshing = False

    @classmethod
    def load(cls, env_path: Path, owner_token: str = "", **kw) -> "AccessPolicy":
        try:
            text = env_path.read_text()
        except OSError:
            text = ""
        tokens, wifi, problems = parse_env(text)
        for p in problems:
            log.warning("Dashboard access: %s", p)
        return cls(owner_token, tokens, wifi, problems=problems, **kw)

    # ---- state ---------------------------------------------------------------------------------------
    @property
    def configured(self) -> bool:
        """Is there any token at all? If not, the stream stays on this Pi only."""
        return bool(self.owner_token or self.tokens)

    def _lookup(self) -> None:
        try:
            ssid = self._reader()
        except Exception:
            ssid = None
        with self._lock:
            self._cache = (self._clock(), ssid)
            self._refreshing = False

    def wifi(self) -> str | None:
        """The current network name. Re-read at most every 10 seconds, and never while holding up other requests:
        a stale answer is served while one background thread looks again (nmcli can take seconds)."""
        with self._lock:
            now = self._clock()
            fresh = now - self._cache[0] <= 10
            if fresh or self._refreshing:
                return self._cache[1]
            first = self._cache[0] < -1e8
            self._refreshing = True
        if first or not self._background:
            self._lookup()                       # nothing to serve yet (or tests): wait for the answer
        else:
            threading.Thread(target=self._lookup, name="wifi-lookup", daemon=True).start()
        with self._lock:
            return self._cache[1]

    def valid(self) -> dict[str, str]:
        """name -> secret for every token that works right now."""
        out = {}
        if self.owner_token:
            out[OWNER] = self.owner_token
        ssid = self.wifi()
        if ssid is not None:
            for name in self.wifi_map.get(ssid, []):
                out.setdefault(name, self.tokens[name])
        return out

    def check(self, given: str, strong: bool = False) -> str | None:
        """The name of the person this token belongs to, or None. `strong` also demands 8+ characters."""
        got = given.encode()
        found = None
        for name, secret in self.valid().items():          # compare against all of them, so timing says nothing
            if hmac.compare_digest(got, secret.encode()) and found is None and (not strong or len(secret) >= MIN_LENGTH):
                found = name
        return found

    def can_run_dashboard(self) -> bool:
        """Is there any token long enough to protect something that can move the robot?"""
        return any(len(s) >= MIN_LENGTH for s in [self.owner_token, *self.tokens.values()])

    def describe(self) -> str:
        """For /access: the network and which names work on it. Never the secrets."""
        ssid = self.wifi()
        names = sorted(self.valid())
        parts = [f"Wi-Fi: {ssid if ssid else 'none (wired, or unknown)'}",
                 f"tokens that work right now: {', '.join(names) if names else 'none'}"]
        elsewhere = sorted({n for s, ns in self.wifi_map.items() if s != ssid for n in ns} - set(names))
        if elsewhere:
            parts.append(f"tied to other networks: {', '.join(elsewhere)}")
        if self.problems:
            parts.append("problems: " + "; ".join(self.problems))
        return " | ".join(parts)


class Lockout:
    """Stops guessing: after 8 wrong tries in a minute an address is refused for the rest of that minute."""

    def __init__(self, limit: int = 8, window: float = 60.0, clock=time.monotonic):
        self.limit, self.window, self._clock = limit, window, clock
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def blocked(self, who: str) -> bool:
        with self._lock:
            now = self._clock()
            recent = [t for t in self._fails.get(who, []) if now - t < self.window]
            self._fails[who] = recent
            if not recent:
                self._fails.pop(who, None)
            return len(recent) >= self.limit

    def failed(self, who: str) -> None:
        with self._lock:
            self._fails.setdefault(who, []).append(self._clock())
            if len(self._fails) > 1000:                 # a flood from many addresses must not grow memory without end
                oldest = min(self._fails, key=lambda k: self._fails[k][-1])
                self._fails.pop(oldest, None)
