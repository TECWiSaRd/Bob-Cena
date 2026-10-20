"""A shared console: several people use the same running Bob, each from their own Pi login, without a shell.

Bob (the server) listens on a local socket. A friend runs `bob-console`, which shows the same screen as the
real console. The operating system tells Bob who is connecting (SO_PEERCRED), so nobody can claim to be
someone else, and what each person may do depends on their Linux groups:

    owner (the account Bob runs as)   everything, including /quit
    operators group                    every command except those listed in `deny` (default: quit)
    viewers group                      watch only, plus the emergency stop

Everything a person types is recorded under their name (log and timeline). The protocol is one JSON object per
line. This file has both halves (server and client) and uses only the standard library, so the client can be
copied somewhere every user can read it (install_remote.sh does that).
"""
from __future__ import annotations

import json
import logging
import os
import queue
import socket
import stat
import struct
import threading
import time
from collections import deque
from types import SimpleNamespace

log = logging.getLogger("bob.remote")

MAX_LINE = 4096            # the longest message either side accepts
BACKLOG = 200              # log lines a new client is sent so it isn't blank
PEERCRED = getattr(socket, "SO_PEERCRED", None)


def encode(obj: dict) -> bytes:
    return (json.dumps(obj, separators=(",", ":")) + "\n").encode()


# =====================================================================================================
# Server: lives inside Bob
# =====================================================================================================
def peer_identity(conn) -> tuple[int, str, set[str]] | None:
    """(uid, user name, group names) of the process on the other end of a local socket, or None if unknown."""
    if PEERCRED is None:
        return None
    import grp
    import pwd
    _pid, uid, gid = struct.unpack("iII", conn.getsockopt(socket.SOL_SOCKET, PEERCRED, struct.calcsize("iII")))
    try:
        name = pwd.getpwuid(uid).pw_name
    except KeyError:
        return None
    groups = set()
    for g in os.getgrouplist(name, gid):
        try:
            groups.add(grp.getgrgid(g).gr_name)
        except KeyError:
            pass
    return uid, name, groups


class Client:
    def __init__(self, conn, name: str, role: str):
        self.conn, self.name, self.role = conn, name, role
        self.out: queue.Queue = queue.Queue(maxsize=1000)
        self.alive = True
        self.since = time.time()
        self.tokens, self.last = 100.0, time.monotonic()

    def send(self, obj: dict) -> None:
        """Queue a message. A client that can't keep up loses its OLDEST lines (the newest matter most) and never slows Bob."""
        for _ in range(2):
            try:
                self.out.put_nowait(obj)
                return
            except queue.Full:
                try:
                    self.out.get_nowait()
                except queue.Empty:
                    pass

    def allow(self) -> bool:
        """A simple rate limit: 60 messages a second sustained, bursts of 100."""
        now = time.monotonic()
        self.tokens = min(100.0, self.tokens + (now - self.last) * 60)
        self.last = now
        if self.tokens < 1:
            return False
        self.tokens -= 1
        return True


class RemoteConsole:
    def __init__(self, cfg, ctrl, logbuf, identify=peer_identity):
        self.cfg, self.ctrl, self.logbuf, self._identify = cfg, ctrl, logbuf, identify
        self.owner_uid = os.getuid()
        self.clients: list[Client] = []
        self._lock = threading.Lock()
        self._sock: socket.socket | None = None
        self._halt = threading.Event()
        self.problem = ""

    # ---- lifecycle ----------------------------------------------------------------------------------
    def start(self) -> None:
        if not self.cfg.enabled:
            return
        if self._identify is peer_identity and PEERCRED is None:
            self.problem = "the shared console needs Linux (it identifies users through the operating system)"
            log.warning("Shared console off: %s", self.problem)
            return
        path = self.cfg.socket
        try:
            self._prepare_path(path)
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            old = os.umask(0)
            try:
                sock.bind(path)
            finally:
                os.umask(old)
            os.chmod(path, 0o666)          # anyone may connect; who may DO anything is decided by group membership
            sock.listen(8)
            sock.settimeout(0.5)
        except OSError as e:
            self.problem = f"can't open {path}: {e}"
            log.warning("Shared console off: %s", self.problem)
            return
        self._sock = sock
        self.logbuf.listeners.append(self._on_log)
        threading.Thread(target=self._accept_loop, name="remote-accept", daemon=True).start()
        threading.Thread(target=self._status_loop, name="remote-status", daemon=True).start()
        log.info("Shared console on %s (operators: %s; viewers: %s)", path,
                 ", ".join(self.cfg.operators) or "none", ", ".join(self.cfg.viewers) or "none")

    @staticmethod
    def _prepare_path(path: str) -> None:
        """Remove a leftover socket from a crashed Bob, but never anything else, and never another Bob's."""
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            return
        if not stat.S_ISSOCK(st.st_mode) or st.st_uid != os.getuid():
            raise OSError("something else is already at that path")
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.settimeout(1)
            probe.connect(path)
        except OSError:
            os.unlink(path)               # nobody is listening: a stale file
            return
        finally:
            probe.close()
        raise OSError("another Bob is already using it")

    def stop(self) -> None:
        self._halt.set()
        if self._on_log in self.logbuf.listeners:
            self.logbuf.listeners.remove(self._on_log)
        with self._lock:
            for c in self.clients:
                c.alive = False
                try:
                    c.conn.close()
                except OSError:
                    pass
        if self._sock:
            try:
                self._sock.close()
                os.unlink(self.cfg.socket)
            except OSError:
                pass

    # ---- who is connected ----------------------------------------------------------------------------
    def describe(self) -> str:
        if not self.cfg.enabled:
            return "off"
        if self.problem:
            return self.problem
        with self._lock:
            who = [f"{c.name} ({c.role})" for c in self.clients]
        return f"on {self.cfg.socket}; " + (", ".join(who) if who else "nobody attached")

    def role_for(self, uid: int, name: str, groups: set[str]) -> str | None:
        if uid == self.owner_uid:
            return "owner"
        if groups & set(self.cfg.operators):
            return "operator"
        if groups & set(self.cfg.viewers):
            return "viewer"
        return None

    # ---- connections ---------------------------------------------------------------------------------
    def _accept_loop(self) -> None:
        while not self._halt.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), name="remote-client", daemon=True).start()

    def _serve(self, conn) -> None:
        conn.settimeout(30)
        client = None
        try:
            ident = self._identify(conn)
            role = self.role_for(*ident) if ident else None
            if role is None:
                who = ident[1] if ident else "this account"
                conn.sendall(encode({"type": "error", "text": f"{who} isn't allowed: ask the owner to add you to the "
                                                              f"'{(self.cfg.operators or ['operators'])[0]}' group"}))
                log.warning("Shared console: refused %s", who)
                return
            client = Client(conn, ident[1], role)
            with self._lock:
                if len(self.clients) >= self.cfg.max_clients:
                    conn.sendall(encode({"type": "error", "text": "too many people are attached"}))
                    return
                self.clients.append(client)
            log.info("Shared console: %s attached (%s)", client.name, role)
            client.send({"type": "hello", "user": client.name, "role": role})
            for level, tag, line in list(self.logbuf.lines)[-BACKLOG:]:
                client.send({"type": "log", "level": level, "tag": tag, "line": line})
            self._push_status(client, force=True)
            threading.Thread(target=self._writer, args=(client,), daemon=True).start()
            self._reader(client)
        except (OSError, ValueError):
            pass
        finally:
            if client:
                client.alive = False
                with self._lock:
                    if client in self.clients:
                        self.clients.remove(client)
                log.info("Shared console: %s left", client.name)
            try:
                conn.close()
            except OSError:
                pass

    def _writer(self, client: Client) -> None:
        while client.alive and not self._halt.is_set():
            try:
                obj = client.out.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                client.conn.sendall(encode(obj))
            except OSError:
                client.alive = False
                return

    def _reader(self, client: Client) -> None:
        buf = b""
        client.conn.settimeout(None)
        while client.alive and not self._halt.is_set():
            data = client.conn.recv(4096)
            if not data:
                return
            buf += data
            if len(buf) > 8 * MAX_LINE and b"\n" not in buf:
                return                                # not a Bob client: hang up
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if len(line) > MAX_LINE:
                    client.send({"type": "notice", "text": "message too long"})
                    continue
                if not client.allow():
                    continue                          # too fast: ignore the excess
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if isinstance(msg, dict):
                    self._handle(client, msg)

    # ---- what clients may do ---------------------------------------------------------------------------
    def _handle(self, client: Client, msg: dict) -> None:
        kind = msg.get("type")
        ctrl = self.ctrl
        if kind == "estop":                           # anyone attached may stop him
            ctrl.estop(f"shared console: {client.name}")
            return
        if client.role == "viewer":
            power = getattr(ctrl, "power", None)
            may_power_off = (kind == "line" and str(msg.get("text", "")).strip().lower().startswith("/shutdown")
                             and power is not None and power.allows("viewer"))
            if not may_power_off:
                if kind in ("line", "manual", "ptt", "drive_stop", "leave_drive"):
                    client.send({"type": "notice", "text": "view-only: you can watch and use the emergency stop (Space)"})
                return
        if kind == "line":
            text = str(msg.get("text", ""))[:500]
            if not text.strip():
                return
            if text.startswith("/"):
                cmd = text[1:].split(None, 1)[0].lower() if len(text) > 1 else ""
                if client.role != "owner" and cmd in {d.lower() for d in self.cfg.deny}:
                    client.send({"type": "notice", "text": f"/{cmd} is only for the owner"})
                    return
                log.info("> [%s] %s", client.name, text)
            try:
                out = ctrl.handle(text, by=client.name, role=client.role)
            except Exception as e:
                out = f"error: {e}"
            if out:
                log.info("%s", out)
        elif kind == "manual":
            if ctrl.drive_mode:
                try:
                    left, right = (max(-1.0, min(1.0, float(msg.get(k, 0)))) for k in ("l", "r"))
                except (TypeError, ValueError):
                    return
                ctrl.manual(left, right, 0.6)
        elif kind == "drive_stop":
            ctrl.drive.stop()
        elif kind == "leave_drive":
            ctrl.drive.stop()
            ctrl.drive_mode = False
            log.info("%s left manual drive - AI still paused, /resume to hand back control", client.name)
        elif kind == "ptt":
            log.info("%s", ctrl.listener.ptt_toggle())

    # ---- what clients see ------------------------------------------------------------------------------
    def _on_log(self, level: int, tag: str, line: str) -> None:
        with self._lock:
            targets = list(self.clients)
        for c in targets:
            c.send({"type": "log", "level": level, "tag": tag, "line": line})

    def _status(self) -> dict:
        ctrl = self.ctrl
        return {"type": "status", "text": ctrl.status_line(), "estop": ctrl.drive.estop.is_set(),
                "drive_mode": bool(ctrl.drive_mode)}

    def _push_status(self, client: Client, force: bool = False) -> None:
        status = self._status()
        if force or status != getattr(client, "_last_status", None):
            client._last_status = status
            client.send(status)

    def _status_loop(self) -> None:
        while not self._halt.wait(0.4):
            with self._lock:
                targets = list(self.clients)
            for c in targets:
                try:
                    self._push_status(c)
                except Exception:
                    pass


# =====================================================================================================
# Client: what a friend runs (the same screen, fed over the socket)
# =====================================================================================================
class RemoteLog:
    """Looks like the console's LogBuffer to the screen code."""

    def __init__(self, maxlen: int = 3000):
        self.lines: deque = deque(maxlen=maxlen)
        self.listeners: list = []


class RemoteController:
    """Looks like the Controller to the screen code, but every action is a message to Bob."""

    def __init__(self, path: str, owner_uid: int | None = None):
        self.path = path
        self.log = RemoteLog()
        self.quit = threading.Event()
        self._drive_mode = False
        self._status = "connecting..."
        self._estop = False
        self.user, self.role = "?", "?"
        self.connected = False
        self._lock = threading.Lock()
        self.drive = SimpleNamespace(estop=SimpleNamespace(is_set=lambda: self._estop), stop=lambda: self._send({"type": "drive_stop"}))
        self.listener = SimpleNamespace(ptt_toggle=lambda: (self._send({"type": "ptt"}), "")[1])
        self._connect(owner_uid)

    def _connect(self, owner_uid: int | None) -> None:
        if owner_uid is not None:                    # don't talk to a socket someone else put there
            st = os.stat(self.path)
            if st.st_uid != owner_uid:
                raise ConnectionError("that socket isn't owned by Bob's account: refusing to connect")
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.path)
        self.connected = True
        threading.Thread(target=self._read, name="remote-read", daemon=True).start()

    def _send(self, obj: dict) -> None:
        if not self.connected:
            return
        try:
            with self._lock:
                self.sock.sendall(encode(obj))
        except OSError:
            self._lost("connection lost")

    def _lost(self, why: str) -> None:
        if self.connected:
            self.connected = False
            self.log.lines.append((40, "SYS", f"{why}: Bob closed the shared console. Press Ctrl-C to leave."))

    def _read(self) -> None:
        buf = b""
        try:
            while True:
                data = self.sock.recv(65536)
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        continue
                    self._apply(msg)
        except OSError:
            pass
        self._lost("disconnected")

    def _apply(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "log":
            self.log.lines.append((int(msg.get("level", 20)), str(msg.get("tag", "")), str(msg.get("line", ""))))
        elif kind == "status":
            self._status, self._estop = str(msg.get("text", "")), bool(msg.get("estop"))
            self._drive_mode = bool(msg.get("drive_mode"))
        elif kind == "hello":
            self.user, self.role = msg.get("user", "?"), msg.get("role", "?")
        elif kind in ("notice", "error"):
            self.log.lines.append((30 if kind == "notice" else 40, "SYS", str(msg.get("text", ""))))
            if kind == "error":
                self.connected = False

    # ---- what the screen code calls ----------------------------------------------------------------------
    @property
    def drive_mode(self) -> bool:
        return self._drive_mode

    @drive_mode.setter
    def drive_mode(self, value: bool) -> None:
        if not value:
            self._send({"type": "leave_drive"})
        self._drive_mode = value

    def status_line(self) -> str:
        who = f"  |  {self.user} ({self.role}{', view only' if self.role == 'viewer' else ''})"
        return (self._status if self.connected else " DISCONNECTED ") + who

    def handle(self, line: str):
        self._send({"type": "line", "text": line})
        return None                                   # the answer arrives in the log, for everyone to see

    def estop(self, source: str = "console") -> None:
        self._send({"type": "estop"})

    def manual(self, left: float, right: float, seconds: float, blocking: bool = False) -> str:
        self._send({"type": "manual", "l": left, "r": right})
        return ""


def run_client(path: str, owner: str | None = None) -> int:
    import pwd
    uid = None
    if owner:
        try:
            uid = pwd.getpwnam(owner).pw_uid
        except KeyError:
            print(f"unknown owner account '{owner}'")
            return 1
    try:
        remote = RemoteController(path, uid)
    except FileNotFoundError:
        print(f"Bob isn't running, or the shared console is off ({path} not found).")
        return 1
    except (ConnectionError, OSError) as e:
        print(f"can't connect to Bob: {e}")
        return 1
    import curses

    from console import ConsoleUI

    def ui(scr):
        screen = ConsoleUI(scr, remote, remote.log)
        screen.loop()

    os.environ.setdefault("ESCDELAY", "25")
    try:
        curses.wrapper(ui)
    except KeyboardInterrupt:
        pass
    finally:
        remote.quit.set()
    return 0


if __name__ == "__main__":
    import argparse
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser(description="Attach to the running Bob's shared console")
    ap.add_argument("--socket", default="/tmp/bob-console.sock")
    ap.add_argument("--owner", help="the account Bob runs as: refuse sockets owned by anyone else")
    args = ap.parse_args()
    sys.exit(run_client(args.socket, args.owner))
