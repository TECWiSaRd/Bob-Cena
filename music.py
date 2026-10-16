"""Bob's sound system: a Bluetooth speaker and an AirPlay receiver that share one speaker with each other
and with Bob's own voice.

How the pieces fit (all on the Pi):

  * PipeWire is the mixer. Bluetooth audio (BlueZ -> PipeWire), AirPlay audio (shairport-sync -> PipeWire)
    and Bob's own voice all play into the same output, so they mix instead of fighting over the device.
  * This module watches PipeWire for the music streams, and:
      - ducks them while Bob speaks (they fade down, then back up),
      - makes the newest source win: a second source pauses the first (so they don't play over each other),
      - lets Bob (and you) press play / pause / next / previous and set the volume, using the phone's own
        remote-control channel for each source (Bluetooth AVRCP through BlueZ, AirPlay through shairport-sync).
  * Pairing a new Bluetooth phone is only possible for a short window that you open.

Nothing here can be tested without the real services, so every external tool goes through small helper
classes (Runner, Bus) that tests replace with stand-ins. See install_music.sh for the one-time system setup.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("bob.music")

BLUEZ = "org.bluez"
SHAIRPORT = "org.gnome.ShairportSync"
SHAIRPORT_PATH = "/org/gnome/ShairportSync"
KINDS = ("bluetooth", "airplay")
LABEL = {"bluetooth": "Bluetooth", "airplay": "AirPlay"}
BT_METHODS = {"play": "Play", "pause": "Pause", "next": "Next", "previous": "Previous", "stop": "Stop"}
AP_METHODS = {"play": "Play", "pause": "Pause", "next": "Next", "previous": "Previous", "stop": "Stop"}
MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")


def clean(text, n: int = 80) -> str:
    """Track names come from other people's phones: flatten them to one short line of plain text."""
    return " ".join("".join(c if c.isprintable() else " " for c in str(text)).split())[:n]


def _plain(v):
    """Turn D-Bus values (which subclass the Python types) and nested containers into plain Python."""
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if isinstance(v, bool):
        return bool(v)
    if isinstance(v, int):
        return int(v)
    if isinstance(v, float):
        return float(v)
    return str(v) if v is not None else None


def pick(meta: dict, *words: str) -> str:
    """First metadata value whose key contains one of the words (keys differ between sources)."""
    for key, value in (meta or {}).items():
        if any(w in key.lower() for w in words):
            if isinstance(value, list):
                value = ", ".join(str(x) for x in value)
            if value:
                return clean(value)
    return ""


# ------------------------------------------------------------------------------------------------
# External-world helpers (replaced in tests)
# ------------------------------------------------------------------------------------------------
class Runner:
    def has(self, command: str) -> bool:
        return shutil.which(command) is not None

    def run(self, cmd: list[str], timeout: float = 4.0) -> tuple[int, str]:
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return p.returncode, p.stdout
        except (OSError, subprocess.TimeoutExpired):
            return 127, ""

    def start(self, cmd: list[str]):
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class DbusBus:
    """A D-Bus connection through python-dbus (apt: python3-dbus). Calls time out after 3 seconds."""

    def __init__(self, which: str):
        import dbus  # raises ImportError if python3-dbus isn't installed
        uid = os.getuid()
        os.environ.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
        os.environ.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{uid}/bus")
        self._dbus = dbus
        self._bus = dbus.SystemBus() if which == "system" else dbus.SessionBus()

    def managed_objects(self, service: str) -> dict:
        om = self._dbus.Interface(self._bus.get_object(service, "/"), "org.freedesktop.DBus.ObjectManager")
        return _plain(om.GetManagedObjects(timeout=3))

    def get_all(self, service: str, path: str, iface: str) -> dict:
        props = self._dbus.Interface(self._bus.get_object(service, path), "org.freedesktop.DBus.Properties")
        return _plain(props.GetAll(iface, timeout=3))

    def call(self, service: str, path: str, iface: str, method: str, *args):
        proxy = self._dbus.Interface(self._bus.get_object(service, path), iface)
        return getattr(proxy, method)(*args, timeout=3)


# ------------------------------------------------------------------------------------------------
# PipeWire: finding the music streams and their volumes
# ------------------------------------------------------------------------------------------------
@dataclass
class Node:
    id: int
    name: str
    state: str
    kind: str  # "bluetooth" or "airplay"


def classify(props: dict) -> str:
    media_class = props.get("media.class", "")
    who = " ".join(str(props.get(k, "")) for k in ("node.name", "application.name", "application.process.binary")).lower()
    if "shairport" in who and media_class.startswith("Stream/Output/Audio"):
        return "airplay"
    if (props.get("device.api") == "bluez5" or props.get("api.bluez5.address")) \
            and media_class in ("Audio/Source", "Stream/Output/Audio") \
            and "headset" not in str(props.get("api.bluez5.profile", "")).lower():
        return "bluetooth"
    return ""


class PipeWire:
    def __init__(self, runner: Runner):
        self.r = runner

    @staticmethod
    def installed() -> bool:
        return bool(shutil.which("pw-dump") and shutil.which("wpctl"))

    def music_nodes(self) -> list[Node]:
        rc, out = self.r.run(["pw-dump"])
        if rc != 0:
            return []
        try:
            objects = json.loads(out)
        except ValueError:
            return []
        nodes = []
        for o in objects if isinstance(objects, list) else []:
            if o.get("type") != "PipeWire:Interface:Node":
                continue
            info = o.get("info") or {}
            props = info.get("props") or {}
            kind = classify(props)
            if kind:
                nodes.append(Node(int(o["id"]), str(props.get("node.name", "")), str(info.get("state", "")), kind))
        return nodes

    def get_volume(self, node_id: int) -> float | None:
        rc, out = self.r.run(["wpctl", "get-volume", str(node_id)])
        m = re.search(r"Volume:\s*([0-9.]+)", out)
        return float(m.group(1)) if rc == 0 and m else None

    def set_volume(self, node_id: int, volume: float) -> None:
        self.r.run(["wpctl", "set-volume", "-l", "1.0", str(node_id), f"{max(0.0, volume):.3f}"])

    def set_mute(self, node_id: int, mute: bool) -> None:
        self.r.run(["wpctl", "set-mute", str(node_id), "1" if mute else "0"])


# ------------------------------------------------------------------------------------------------
# Bluetooth (BlueZ) and AirPlay (shairport-sync) remote control and now-playing info
# ------------------------------------------------------------------------------------------------
class Bluez:
    def __init__(self, bus):
        self.bus = bus

    def snapshot(self) -> dict:
        """{"player": {path, status, title, artist, device} or None, "connected": [alias, ...]}"""
        objects = self.bus.managed_objects(BLUEZ)
        connected, player = [], None
        for path, ifaces in objects.items():
            dev = ifaces.get("org.bluez.Device1")
            if dev and dev.get("Connected"):
                connected.append(clean(dev.get("Alias") or dev.get("Name") or path.rsplit("/", 1)[-1], 40))
            mp = ifaces.get("org.bluez.MediaPlayer1")
            if mp and player is None:
                track = mp.get("Track") or {}
                dev_path = mp.get("Device") or path.rsplit("/", 1)[0]
                dev_props = (objects.get(dev_path) or {}).get("org.bluez.Device1") or {}
                player = {"path": path, "status": str(mp.get("Status", "")).lower() or None,
                          "title": pick(track, "title"), "artist": pick(track, "artist"),
                          "device": clean(dev_props.get("Alias") or dev_props.get("Name") or "", 40)}
        return {"player": player, "connected": connected}

    def control(self, action: str, player_path: str | None) -> tuple[bool, str]:
        if action not in BT_METHODS:
            return False, f"Bluetooth can't {action}"
        if not player_path:
            return False, "the phone isn't offering playback controls over Bluetooth (use the phone itself)"
        try:
            self.bus.call(BLUEZ, player_path, "org.bluez.MediaPlayer1", BT_METHODS[action])
            return True, "ok"
        except Exception as e:
            return False, f"Bluetooth {action} failed ({str(e)[:80]})"

    def paired(self) -> list[tuple[str, str]]:
        out = []
        for path, ifaces in self.bus.managed_objects(BLUEZ).items():
            dev = ifaces.get("org.bluez.Device1")
            if dev and dev.get("Paired"):
                out.append((str(dev.get("Address", "")), clean(dev.get("Alias") or dev.get("Name") or "", 40)))
        return out


class AirPlay:
    RC = SHAIRPORT + ".RemoteControl"

    def __init__(self, bus):
        self.bus = bus

    def snapshot(self) -> dict | None:
        try:
            main = self.bus.get_all(SHAIRPORT, SHAIRPORT_PATH, SHAIRPORT)
        except Exception:
            return None  # the AirPlay service isn't running, or was built without its D-Bus interface
        snap = {"active": bool(main.get("Active")), "state": None, "title": "", "artist": "", "device": "", "remote": False}
        try:
            rc = self.bus.get_all(SHAIRPORT, SHAIRPORT_PATH, self.RC)
            snap["state"] = (str(rc.get("PlayerState") or "").lower() or None)
            snap["remote"] = bool(rc.get("Available"))
            snap["device"] = clean(rc.get("ClientName") or "", 40)
            meta = rc.get("Metadata") or {}
            snap["title"], snap["artist"] = pick(meta, "title"), pick(meta, "artist")
        except Exception:
            pass
        return snap

    def control(self, action: str, remote_ok: bool) -> tuple[bool, str]:
        if action not in AP_METHODS:
            return False, f"AirPlay can't {action}"
        if not remote_ok:
            return False, "this AirPlay sender doesn't allow remote control (use the phone itself)"
        try:
            self.bus.call(SHAIRPORT, SHAIRPORT_PATH, self.RC, AP_METHODS[action])
            return True, "ok"
        except Exception as e:
            return False, f"AirPlay {action} failed ({str(e)[:80]})"


# ------------------------------------------------------------------------------------------------
# The coordinator
# ------------------------------------------------------------------------------------------------
@dataclass
class SourceState:
    playing: bool = False
    since: float = 0.0
    title: str = ""
    artist: str = ""
    device: str = ""
    present: bool = False          # a phone is connected / the AirPlay service is up
    can_control: bool = False
    control_ref: str | None = None  # BlueZ player path (Bluetooth)
    muted_by_us: bool = False
    nodes: list[Node] = field(default_factory=list)


class MusicSystem(threading.Thread):
    def __init__(self, cfg, state_dir: Path, name: str = "Bob", runner=None, bluez=None, airplay=None,
                 pipewire=None, clock=time.monotonic, sleep=time.sleep):
        super().__init__(name="music", daemon=True)
        self.cfg, self.name_ = cfg, name
        self.state_dir = Path(state_dir)
        self.r = runner or Runner()
        self.pw = pipewire if pipewire is not None else PipeWire(self.r)
        self.bluez, self.airplay = bluez, airplay
        self._clock, self._sleep = clock, sleep
        self.src = {k: SourceState() for k in KINDS}
        self.current: str | None = None   # the source Bob controls: playing now, else the last one that played
        self.volume_set: float | None = None
        self.pairing = False
        self.problems: list[str] = []
        self._lock = threading.RLock()
        self._quit = threading.Event()
        self._seen: set[int] = set()
        self._duck_depth = 0
        self._duck_saved: dict[int, tuple[str, float]] = {}
        self._restore_timer: threading.Timer | None = None
        self._duck_file = self.state_dir / "music_duck.json"
        self._init_backends()

    # ---- setup ----------------------------------------------------------------------------------
    def _init_backends(self) -> None:
        cfg = self.cfg
        if self.bluez is None and cfg.bluetooth:
            try:
                self.bluez = Bluez(DbusBus("system"))
            except Exception as e:
                self.problems.append(f"Bluetooth control unavailable ({e}); apt: python3-dbus")
        if self.airplay is None and cfg.airplay:
            try:
                self.airplay = AirPlay(DbusBus(cfg.airplay_bus))
            except Exception as e:
                self.problems.append(f"AirPlay control unavailable ({e})")
        if not self.pw.installed() and isinstance(self.pw, PipeWire):
            self.problems.append("PipeWire tools (pw-dump, wpctl) not found: run install_music.sh")

    def run(self) -> None:
        self.recover()
        while not self._quit.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("music poll failed")
            self._quit.wait(max(0.3, self.cfg.poll_seconds))

    def stop(self) -> None:
        self._quit.set()
        self._finish_duck(immediate=True)

    @property
    def playing(self) -> bool:
        return any(s.playing for s in self.src.values())

    # ---- polling and arbitration ----------------------------------------------------------------
    def tick(self) -> None:
        now = self._clock()
        nodes = self.pw.music_nodes()
        by_kind = {k: [n for n in nodes if n.kind == k] for k in KINDS}
        bt = ap = None
        if self.bluez and self.cfg.bluetooth:
            try:
                bt = self.bluez.snapshot()
            except Exception:
                bt = None
        if self.airplay and self.cfg.airplay:
            ap = self.airplay.snapshot()
        with self._lock:
            for kind in KINDS:
                s, ns = self.src[kind], by_kind[kind]
                running = any(n.state == "running" for n in ns)
                s.nodes = ns
                if kind == "bluetooth":
                    player = (bt or {}).get("player")
                    status = player["status"] if player else None
                    playing = (status == "playing") if status else running
                    s.present = bool((bt or {}).get("connected")) or bool(ns)
                    s.can_control = bool(player)
                    s.control_ref = player["path"] if player else None
                    s.title, s.artist = (player["title"], player["artist"]) if player else ("", "")
                    s.device = (player["device"] if player and player["device"] else
                                ((bt or {}).get("connected") or [""])[0])
                else:
                    state = ap["state"] if ap else None
                    playing = (state == "playing") if state else running
                    s.present = ap is not None or bool(ns)
                    s.can_control = bool(ap and ap["remote"])
                    s.title, s.artist, s.device = (ap["title"], ap["artist"], ap["device"]) if ap else ("", "", "")
                if playing and not s.playing:
                    s.since = now
                    log.info("MUSIC %s started%s", LABEL[kind], f" ({s.title})" if s.title else "")
                if s.playing and not playing:
                    log.info("MUSIC %s stopped", LABEL[kind])
                s.playing = playing
                if playing:
                    self.current = kind
            self._apply_initial_volume(nodes)
            self._ensure_ducked(nodes)
            if self.cfg.exclusive:
                self._arbitrate()

    def _apply_initial_volume(self, nodes: list[Node]) -> None:
        """A phone at full volume would be shockingly loud: start each new music stream at a modest level."""
        for n in nodes:
            if n.id in self._seen:
                continue
            self._seen.add(n.id)
            if self.cfg.initial_volume is not None and not self._duck_depth:
                self.pw.set_volume(n.id, min(self.cfg.initial_volume, self.cfg.max_volume))
        self._seen &= {n.id for n in nodes}   # forget streams that are gone

    def _arbitrate(self) -> None:
        a, b = self.src["bluetooth"], self.src["airplay"]
        if a.playing and b.playing:
            older, newer = ("bluetooth", "airplay") if a.since <= b.since else ("airplay", "bluetooth")
            s = self.src[older]
            if not s.muted_by_us:
                ok, why = self._control_source(older, "pause")
                if ok:
                    log.info("MUSIC %s started, so %s was paused", LABEL[newer], LABEL[older])
                else:   # can't pause it: silence its stream instead so the two don't play over each other
                    for n in s.nodes:
                        self.pw.set_mute(n.id, True)
                    s.muted_by_us = True
                    log.info("MUSIC %s started; muted %s (%s)", LABEL[newer], LABEL[older], why)
        for kind in KINDS:   # once the newcomer stops, let a muted source be heard again
            s, other = self.src[kind], self.src["airplay" if kind == "bluetooth" else "bluetooth"]
            if s.muted_by_us and not other.playing:
                for n in s.nodes:
                    self.pw.set_mute(n.id, False)
                s.muted_by_us = False

    # ---- ducking --------------------------------------------------------------------------------
    @contextmanager
    def duck(self):
        """Lower the music while Bob talks, then bring it back."""
        self._begin_duck()
        try:
            yield
        finally:
            self._end_duck()

    def _music_nodes(self) -> list[Node]:
        return [n for k in KINDS for n in self.src[k].nodes]

    def _begin_duck(self) -> None:
        with self._lock:
            if self._restore_timer:
                self._restore_timer.cancel()
                self._restore_timer = None
            self._duck_depth += 1
            if self._duck_depth == 1 and self.playing:
                self._ensure_ducked(self._music_nodes(), ramp=True)

    def _ensure_ducked(self, nodes: list[Node], ramp: bool = False) -> None:
        """Duck any music stream that isn't ducked yet (a new track can create a new stream mid-speech)."""
        if not self._duck_depth:
            return
        todo = [n for n in nodes if n.id not in self._duck_saved]
        for n in todo:
            v = self.pw.get_volume(n.id)
            if v is not None:
                self._duck_saved[n.id] = (n.name, v)
        if todo:
            self._write_duck_file()
            self._ramp({n.id: (self._duck_saved[n.id][1], self._duck_saved[n.id][1] * self.cfg.duck_level)
                        for n in todo if n.id in self._duck_saved}, steps=4 if ramp else 1)

    def _end_duck(self) -> None:
        with self._lock:
            self._duck_depth = max(0, self._duck_depth - 1)
            if self._duck_depth == 0 and self._duck_saved:
                # wait a moment: Bob often speaks twice in a row, and the music shouldn't bounce between
                self._restore_timer = threading.Timer(self.cfg.duck_hold_s, self._finish_duck)
                self._restore_timer.daemon = True
                self._restore_timer.start()

    def _finish_duck(self, immediate: bool = False) -> None:
        with self._lock:
            if self._duck_depth or not self._duck_saved:
                return
            current = {n.id for n in self._music_nodes()}
            targets = {i: (v * self.cfg.duck_level, v) for i, (_, v) in self._duck_saved.items() if i in current}
            self._ramp(targets, steps=1 if immediate else 5)
            self._duck_saved.clear()
            self._remove_duck_file()

    def _ramp(self, plan: dict[int, tuple[float, float]], steps: int) -> None:
        for step in range(1, steps + 1):
            for node_id, (start, end) in plan.items():
                self.pw.set_volume(node_id, start + (end - start) * step / steps)
            if step < steps:
                self._sleep(0.04)

    def _write_duck_file(self) -> None:
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            self._duck_file.write_text(json.dumps({name: v for name, v in self._duck_saved.values()}))
        except OSError:
            pass

    def _remove_duck_file(self) -> None:
        try:
            self._duck_file.unlink()
        except OSError:
            pass

    def recover(self) -> None:
        """If Bob died while the music was ducked, the saved volumes are still on disk: put them back."""
        try:
            saved = json.loads(self._duck_file.read_text())
        except (OSError, ValueError):
            return
        self._remove_duck_file()
        if not isinstance(saved, dict):
            return
        for n in self.pw.music_nodes():
            if n.name in saved:
                self.pw.set_volume(n.id, float(saved[n.name]))
                log.info("MUSIC restored %s volume after an interrupted duck", n.name)

    # ---- control (Bob, the console and the dashboard) -------------------------------------------
    def _pick_source(self) -> str | None:
        playing = [k for k in KINDS if self.src[k].playing]
        if playing:
            return max(playing, key=lambda k: self.src[k].since)
        if self.current and self.src[self.current].present:
            return self.current
        present = [k for k in KINDS if self.src[k].present]
        return present[0] if present else None

    def _control_source(self, kind: str, action: str) -> tuple[bool, str]:
        s = self.src[kind]
        if kind == "bluetooth":
            return self.bluez.control(action, s.control_ref) if self.bluez else (False, "Bluetooth control isn't available")
        return self.airplay.control(action, s.can_control) if self.airplay else (False, "AirPlay control isn't available")

    def control(self, action: str) -> tuple[bool, str]:
        if action not in ("play", "pause", "next", "previous"):
            return False, f"unknown music action {action!r}"
        with self._lock:
            kind = self._pick_source()
        if kind is None:
            return False, "nothing is connected: start playing from a phone over Bluetooth or AirPlay"
        ok, why = self._control_source(kind, action)
        if ok:
            return True, f"{action} sent to {LABEL[kind]}"
        return False, f"couldn't {action} {LABEL[kind]}: {why}"

    def set_volume(self, percent: float) -> tuple[bool, str]:
        """Music volume 0-100, capped by max_volume. Applies to every music stream."""
        level = max(0.0, min(percent / 100.0, self.cfg.max_volume))
        with self._lock:
            nodes = self._music_nodes()
            if not nodes:
                return False, "no music is connected, so there's no volume to change"
            self.volume_set = level
            if self._duck_depth:   # keep the ducked state consistent: the new level becomes the thing to return to
                for n in nodes:
                    self._duck_saved[n.id] = (n.name, level)
                    self.pw.set_volume(n.id, level * self.cfg.duck_level)
                self._write_duck_file()
            else:
                for n in nodes:
                    self.pw.set_volume(n.id, level)
        capped = percent / 100.0 > self.cfg.max_volume
        return True, f"music volume {round(level * 100)}%" + (f" (the limit is {round(self.cfg.max_volume * 100)}%)" if capped else "")

    def current_volume(self) -> float | None:
        with self._lock:
            nodes = self._music_nodes()
            saved = {i: v for i, (_, v) in self._duck_saved.items()}
        for n in nodes:
            v = saved.get(n.id, self.pw.get_volume(n.id))
            if v is not None:
                return v
        return None

    def adjust_volume(self, delta_percent: float) -> tuple[bool, str]:
        cur = self.current_volume()
        if cur is None:
            return False, "no music is connected, so there's no volume to change"
        return self.set_volume(cur * 100 + delta_percent)

    def act(self, action: str, level: float = 0.0) -> tuple[bool, str]:
        """The single entry point for the console, the dashboard and Claude's tool."""
        if action == "status":
            return True, self.describe()
        if action in ("play", "pause", "next", "previous"):
            return self.control(action)
        if action == "volume_up":
            return self.adjust_volume(+10)
        if action == "volume_down":
            return self.adjust_volume(-10)
        if action == "set_volume":
            return self.set_volume(level)
        return False, f"unknown music action {action!r}"

    # ---- reporting ------------------------------------------------------------------------------
    def describe(self) -> str:
        with self._lock:
            bits = []
            for k in KINDS:
                s = self.src[k]
                if s.playing:
                    what = f"'{s.title}'" + (f" by {s.artist}" if s.artist else "") if s.title else "something"
                    bits.append(f"{LABEL[k]}{' (' + s.device + ')' if s.device else ''} is playing {what}"
                                + ("" if s.can_control else " [no remote control from here]"))
                elif s.present:
                    bits.append(f"{LABEL[k]} is connected{' (' + s.device + ')' if s.device else ''} but not playing")
        vol = self.current_volume()
        text = "; ".join(bits) if bits else "nothing connected (pair a phone with Bluetooth, or choose Bob in AirPlay)"
        if vol is not None:
            text += f"; volume {round(vol * 100)}% (limit {round(self.cfg.max_volume * 100)}%)"
        if self.pairing:
            text += "; Bluetooth pairing is open"
        return text

    def summary_line(self) -> str:
        return "" if not (self.playing or any(s.present for s in self.src.values())) else self.describe()

    # ---- Bluetooth pairing ----------------------------------------------------------------------
    def devices(self) -> list[tuple[str, str]]:
        return self.bluez.paired() if self.bluez else []

    def pair(self, seconds: int = 120) -> str:
        """Open a pairing window: discoverable, with an auto-accept agent, then close it again."""
        if not self.cfg.bluetooth:
            return "Bluetooth is switched off in [music]"
        if not self.r.has("bluetoothctl"):
            return "bluetoothctl isn't installed, so I can't open pairing: sudo apt install bluez (./install_music.sh does this)"
        seconds = max(20, min(int(seconds), 300))
        with self._lock:
            if self.pairing:   # set here, not in the thread, so a second request right behind the first sees it
                return "pairing is already open"
            self.pairing = True
        threading.Thread(target=self._pair_window, args=(seconds,), name="bt-pair", daemon=True).start()
        return (f"Bluetooth pairing is open for {seconds} s. On the phone, open Bluetooth settings and choose "
                f"'{self.name_}'. It closes by itself.")

    def _bt(self, *args: str) -> tuple[int, str]:
        return self.r.run(["bluetoothctl", *args], timeout=6)

    def _paired_macs(self) -> set[str]:
        rc, out = self._bt("devices", "Paired")
        if rc != 0 or not out.strip():
            rc, out = self._bt("paired-devices")
        return {m.group(1).upper() for m in re.finditer(r"Device\s+([0-9A-Fa-f:]{17})", out)}

    def _pair_window(self, seconds: int) -> None:
        agent = None
        try:
            before = self._paired_macs()
            self._bt("system-alias", self.name_)
            self._bt("power", "on")
            self._bt("pairable", "on")
            self._bt("discoverable-timeout", str(seconds))
            self._bt("discoverable", "on")
            if self.r.has("bt-agent"):
                agent = self.r.start(["bt-agent", "-c", "NoInputNoOutput"])
            log.info("MUSIC Bluetooth pairing open for %ds", seconds)
            end = self._clock() + seconds
            while self._clock() < end and not self._quit.is_set():
                self._sleep(2)
                new = self._paired_macs() - before
                for mac in new:
                    self._bt("trust", mac)       # so the phone can reconnect by itself later
                    self._bt("connect", mac)
                    log.info("MUSIC paired and trusted %s", mac)
                if new:
                    break
        finally:
            if agent is not None:
                agent.terminate()
            self._bt("discoverable", "off")
            self._bt("pairable", "off")
            self.pairing = False
            log.info("MUSIC Bluetooth pairing closed")

    def forget(self, mac: str) -> str:
        if not MAC_RE.match(mac):
            return "give the device's Bluetooth address, like AA:BB:CC:DD:EE:FF (see /music devices)"
        rc, _ = self._bt("remove", mac.upper())
        return f"removed {mac.upper()}" if rc == 0 else "couldn't remove that device"
