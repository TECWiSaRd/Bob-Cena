#!/usr/bin/env python3
"""Bob - a Claude-driven mini robot for the Raspberry Pi 4B.

    python bob.py              # full robot with the live console
    python bob.py --sim        # no hardware: test the AI loop and console anywhere
    python bob.py --paused     # boot with the AI paused (overrides only)
    python bob.py --headless   # plain log output + commands on stdin
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import signal
import sys
import threading
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import config
from brain import MODEL_ALIASES, PRICES, Brain, Controls, Memory, People
from hardware import SOUNDS, Audio, Camera, Drive
from listen import Listener
from music import MusicSystem
from radio import Radio
from sensors import RangeSensor
from calibrate import Calibrator
from vision import FaceDetector, Follower
from access import AccessPolicy
from stream import StreamServer
from selfcheck import format_report, run_checks
from timeline import Timeline
from index import Index
from home import Home
from power import PowerControl
from gamepad import Gamepad

BASE = Path(__file__).resolve().parent
log = logging.getLogger("bob")
TUNING = BASE / "tuning.json"  # Pi-only live adjustments; overrides config.toml, survives rsync
TUNABLE = ("left_trim", "right_trim", "dc_min_duty")

HELP = """\
Commands (text without a leading / is said to Bob; /ask TEXT makes him answer now, even when paused):
  SPACE on empty line   EMERGENCY STOP (also /estop)
  /clear                release the E-stop (AI stays paused)
  /pause (or /hush)     stop Bob thinking now: cancels the request in progress
  /resume               start autonomous AI ticks again (/think on|off also works)
  /model opus|sonnet|haiku   switch Claude model live (haiku is ~40x cheaper than opus)
  /step                 run one AI tick while paused
  /drive [all]          manual WASD/arrow-key driving for you (pauses AI); 'all' = everyone attached
  /fwd /back /left /right [secs]   quick manual moves
  /move L R SECS        raw wheel speeds -1..1
  /motion on|off        allow / forbid AI movement (AI keeps seeing and talking)
  /camera on|off        turn the camera off: no frames reach Claude or /snap
  /speed 0-1            set the global speed cap
  /trim [left|right X]  drift fix: +0.05 = that wheel 5% faster (/trim reset clears)
  /minduty [X]          lowest motor power that turns the wheels (0-0.9); both are saved on the Pi
  /listen on|off        microphone (also: mode ptt|hands-free, threshold X, wake off|oww|text; /listen alone shows the level)
  /radio                Bluetooth link to the other robot: status. Also: log [n], say <text>, on|off, ai on|off
  /music                Bluetooth/AirPlay speaker: status. Also: play|pause|next|prev, vol N|up|down, pair [secs], devices, forget MAC, ai on|off
  /calibrate turn|straight|show  Bob measures his own turn rates / drift with the camera (add 'go' to run)
  /follow [seconds]     follow the nearest face (default 30 s); /follow off stops it
  /find [seconds]       turn slowly on the spot until a face is seen, then say so (/find off stops)
  /check                one report: camera, motors, audio, mic, stream, sensor, temperature, power, Wi-Fi, disk
  /timeline             record what Bob saw and did (on|off, show [n], clear)
  /search WORDS         search everything Bob has recorded: /search lens covered kind:estop since:2d
  /home                 lights in Bob's room via Home Assistant: status, on, off, ai on|off (may Claude use them?), check
  /locate [seconds]     turn slowly on the spot looking for a room tag, to find out which room he's in (/locate off stops)
  /tags                 what room tags the camera sees right now (point him at a tag to test it)
  /tags min [px|reset]  set how big a tag must look to count: stand him at the farthest distance you want, facing a tag
  /access               the Wi-Fi network Bob is on and which dashboard tokens work on it right now
  /shutdown             power the Pi off (then /shutdown confirm). The Pi can't be switched back on from here
  /who                  who is attached to the shared console (manual 20)
  /where [room|clear]   tell Bob which room he is in (overrides the room sensor); /where alone shows it
  /index                the search index: status, sync, rebuild, ai on|off (may Claude search his history?)
  /range                distance sensor reading; also: on|off, stop <cm>
  /talk (or Tab)        push-to-talk: press to start recording, again to send
  /say TEXT             speak through the speaker
  /sound NAME           play a sound: """ + " ".join(SOUNDS) + """
  /mute /unmute         silence all audio
  /goal [TEXT]          show or set Bob's goal
  /snap                 save a camera photo to captures/
  /notes /forget        show / wipe Bob's long-term notes
  /people               who Bob knows; also: forget <name>, clear
  /effort low|medium|high
  /detach              leave tmux, Bob keeps running (same as Ctrl-B d)
  /quit"""


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            # WIFI[...] and TOKEN_ lines are read by access.py; they stay out of the environment that child programs inherit
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) and not key.startswith("TOKEN_"):
                os.environ.setdefault(key, value.strip().strip("'\""))


TAG_MIN_LIMITS = (15.0, 400.0)   # the room-tag size limit (pixels) /tags min may set
TUNING_LIMITS = {"left_trim": (-0.5, 0.5), "right_trim": (-0.5, 0.5), "dc_min_duty": (0.0, 0.9)}


def load_tuning(drive_cfg, home_cfg=None, extra: dict | None = None) -> dict:
    """Apply tuning.json over config.toml. Returns the saved calibration (turn rates) or {}.

    `extra` collects other saved values (so they are written back later); `home_cfg` gets the room-tag size limit."""
    if not TUNING.exists():
        return {}
    try:
        data = json.loads(TUNING.read_text())
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
        values = {key: max(lo, min(hi, float(data[key])))  # parse everything first: all or nothing
                  for key, (lo, hi) in TUNING_LIMITS.items() if key in data}
        calib = {}
        raw = data.get("calibration")
        if isinstance(raw, dict) and isinstance(raw.get("turn"), dict):
            calib = {"turn": {str(k): float(v) for k, v in raw["turn"].items()}, "cap": float(raw.get("cap", 1.0))}
        for key, value in values.items():
            setattr(drive_cfg, key, value)
        tag_min = data.get("tag_min_px")
        if home_cfg is not None and isinstance(tag_min, (int, float)) and not isinstance(tag_min, bool):
            home_cfg.tag_min_px = max(TAG_MIN_LIMITS[0], min(TAG_MIN_LIMITS[1], float(tag_min)))
            if extra is not None:
                extra["tag_min_px"] = home_cfg.tag_min_px
            log.info("Applied tag_min_px=%g from %s", home_cfg.tag_min_px, TUNING.name)
        if values:
            log.info("Applied %s over config.toml: %s", TUNING.name,
                     ", ".join(f"{k}={v:g}" for k, v in values.items()))
        return calib
    except (ValueError, TypeError, OSError) as e:
        log.warning("Ignoring unreadable %s (%s)", TUNING.name, e)
        return {}


def save_tuning(drive_cfg, calibration: dict | None = None, extra: dict | None = None) -> None:
    data = {k: getattr(drive_cfg, k) for k in TUNABLE}
    data.update(extra or {})
    if calibration:
        data["calibration"] = calibration
    TUNING.write_text(json.dumps(data, indent=1))


class Controller:
    def __init__(self, cfg: config.Config, sim: bool, paused: bool):
        self.cfg = cfg
        self.default_tag_min = cfg.home.tag_min_px      # the config.toml value, for /tags min reset
        self.tuning_extra: dict = {}                    # other saved tuning (the tag size limit)
        self.calibration = load_tuning(cfg.drive, cfg.home, self.tuning_extra)
        self.calibrating = None   # the Calibrator while a calibration run is in progress
        self.quit = threading.Event()
        self._check_lock = threading.Lock()
        self._drive_mode = False
        self.drive_users: set[str] = set()            # who is driving by hand (/drive adds you, /drive all adds everyone attached)
        self._drive_lock = threading.RLock()
        self.gamepad = Gamepad(cfg.gamepad, self) if cfg.gamepad.enabled else None
        self.ranger = RangeSensor(cfg.sensor, sim)
        self.drive = Drive(cfg.drive, sim, self.ranger)
        self.drive.on_estop = self.estop
        self.camera = Camera(cfg.camera, sim)
        self.access = AccessPolicy.load(BASE / ".env", os.environ.get("BOB_STREAM_TOKEN", ""))
        self.stream = StreamServer(cfg.stream, self.camera, self.access) if cfg.stream.enabled else None
        self.audio = Audio(cfg.audio, BASE / "sounds", sim, BASE / "voices")
        self.listener = Listener(cfg.mic, self.heard, self.audio, self.drive)
        self.listener.on_wake = lambda: self.background(self.audio.play, "chirp")
        self.music = MusicSystem(cfg.music, BASE, cfg.radio.name) if cfg.music.enabled else None
        if self.music:
            for problem in self.music.problems:
                log.warning("Music: %s", problem)
            self.audio.duck = self.music.duck      # the music falls while Bob speaks
            self.listener.music_busy = lambda: bool(cfg.music.mic_deaf_while_playing and self.music.playing)
        self.radio = self._make_radio(cfg.radio)
        self.follower = Follower(cfg.follow, cfg.camera.fov_deg, self.camera, self.drive, self.ranger,
                                 lambda: FaceDetector(BASE / "models"))
        self.timeline = Timeline(cfg.timeline, BASE / "logs" / "timeline")
        self._last_manual_event = float("-inf")
        self.index = Index(cfg.index, BASE)
        self.power = PowerControl(cfg.power, sim=sim)
        self.home = Home(cfg.home, os.environ.get("HA_TOKEN", ""))
        self.home.wifi_reader = self.access.wifi
        self.home.on_event = lambda **kw: self.timeline.record("home", **kw)
        self.drive.on_event = lambda why: self.timeline.record("stop", reason=why)
        self.controls = Controls(cfg.brain.goal, auto=not (paused or cfg.brain.start_paused))
        self.controls.calibration = self.calibration
        self.controls.recall_ai = cfg.index.ai
        self.controls.speed_cap = lambda: self.drive.speed_cap
        self.memory = Memory(BASE / "memory.json")
        self.people = People(BASE / "people.json")
        self.brain = Brain(cfg.brain, self.controls, self.memory, self.drive, self.camera, self.audio, self.radio, self.follower, self.people, self.music, self.index, self.home)
        self.brain.timeline = self.timeline

    def _make_radio(self, rc):
        if not rc.enabled:
            return None
        secret = os.environ.get("BOB_RADIO_SECRET", "")
        if len(secret) < 16:
            log.error("Radio disabled: set BOB_RADIO_SECRET in .env to a long random text (16+ characters), "
                      "the same on both robots")
            return None
        try:
            return Radio(rc.name, rc.peer_name, secret, rc.role, rc.peer_address, rc.channel,
                         lambda sender, text: self.controls.post_radio(sender, text),
                         rc.ai_max_per_minute, BASE / "logs" / "radio.jsonl",
                         transport=rc.transport, port=rc.port, bind=rc.bind)
        except ValueError as e:
            log.error("Radio disabled: %s", e)
            return None

    @staticmethod
    def background(fn, *args) -> None:
        """Run an audio call off the console thread; report failures in the log, not on the TUI."""
        def run():
            try:
                fn(*args)
            except Exception as e:
                log.warning("Audio failed: %s", getattr(e, "stderr", None) or e)
        threading.Thread(target=run, daemon=True).start()

    def start(self) -> None:
        log.info("Bob starting - AI %s", "running" if self.controls.auto else "paused")
        self.background(self.audio.play, "startup")
        if self.stream:
            try:
                self.stream.start()
            except OSError as e:
                log.warning("Camera stream not started (%s)", e)
                self.stream = None
        self.index.start()
        self.camera.watch(self.cfg.camera.restart_after_s, self.camera_stuck)
        self.home.attach_camera(self.camera, self.drive)
        self.brain.start()
        self.listener.start()
        if self.gamepad:
            self.gamepad.start()
        if self.music:
            self.music.start()
        if self.radio:
            self.radio.start()

    def music_command(self, words: list[str]) -> str:
        m, c = self.music, self.controls
        if m is None:
            return "music is off: set [music] enabled = true in config.toml (run ./install_music.sh on the Pi first)"
        sub = words[0].lower() if words else "status"
        rest = words[1:]
        if sub == "status":
            text = m.describe() + f"\nBob may control it: {'yes' if c.music_ai else 'NO'}"
            return text + ("\nproblems: " + "; ".join(m.problems) if m.problems else "")
        if sub in ("play", "pause", "next"):
            return m.act(sub)[1]
        if sub in ("prev", "previous"):
            return m.act("previous")[1]
        if sub in ("vol", "volume"):
            if rest and rest[0].lower() in ("up", "down"):
                return m.act("volume_" + rest[0].lower())[1]
            if rest:
                return m.act("set_volume", float(rest[0]))[1]
            v = m.current_volume()
            return f"music volume {round(v * 100)}%" if v is not None else "no music is connected"
        if sub == "pair":
            return m.pair(int(rest[0]) if rest else 120)
        if sub == "devices":
            devs = m.devices()
            return "\n".join(f"{mac}  {alias}" for mac, alias in devs) or "no paired Bluetooth devices"
        if sub == "forget" and rest:
            return m.forget(rest[0])
        if sub == "ai" and rest and rest[0].lower() in ("on", "off"):
            c.music_ai = rest[0].lower() == "on"
            return f"Bob {'may' if c.music_ai else 'may NOT'} control the music"
        return "usage: /music | play | pause | next | prev | vol N|up|down | pair [seconds] | devices | forget MAC | ai on|off"

    def _announce_find(self, session: int) -> None:
        """After a /find: say so out loud if it worked. Runs off the console thread.

        It reads the result of its own session, so a find or follow started right afterwards can't change it."""
        outcome = self.follower.outcome(session, self.cfg.follow.max_seconds + 5)
        if outcome and outcome[0]:
            self.audio.play("chirp")
            self.audio.say("There you are!")

    def home_command(self, words: list[str]) -> str:
        h = self.home
        if not h.enabled:
            return f"Home Assistant isn't set up: {h.problem or 'set enabled = true under [home]'}"
        sub = words[0] if words else "status"
        if sub == "check":
            level, detail = h.check()
            return f"{level}: {detail}"
        if sub == "ai" and len(words) == 2 and words[1] in ("on", "off"):
            self.controls.home_ai = words[1] == "on"
            return f"Bob {'may' if self.controls.home_ai else 'may NOT'} use the lights"
        if sub in ("status", "on", "off"):
            pct = int(words[1]) if sub == "on" and len(words) > 1 and words[1].isdigit() else None
            text, _ = h.act(sub, pct, operator=True)
            return text + f"  (Bob may use the lights himself: {'yes' if self.controls.home_ai else 'NO'})" * (sub == "status")
        return "usage: /home | on [brightness%] | off | check | ai on|off"

    def camera_stuck(self, seconds: float, exit_fn=os._exit) -> None:
        """The camera driver has hung. Stop the wheels, and, when a service will bring Bob back, restart him.

        Nothing can un-hang the driver from inside the program, and a normal shutdown would wait on it too, so Bob
        leaves with a failure code: the tmux loop in bob.service (or systemd) starts a fresh copy a few seconds later.
        """
        log.error("Camera has been stuck for %.0fs", seconds)
        try:
            self.drive.stop()
        except Exception:
            log.exception("Couldn't stop the wheels")
        if os.environ.get("BOB_SUPERVISED") != "1":
            log.error("Not restarting: Bob wasn't started by the service. Restart him yourself (and reboot the Pi if it repeats)")
            return
        log.error("Restarting Bob now (the service brings him back in a few seconds)")
        try:
            self.drive.close()                    # motor driver in standby before the process goes (only on this path)
        except Exception:
            log.exception("Couldn't close the motor driver cleanly")
        for h in logging.getLogger("bob").handlers:
            try:
                h.flush()
            except Exception:
                pass
        exit_fn(75)

    def check_command(self) -> str | None:
        """/check can take many seconds (network lookups, the camera), so it runs beside the console, never inside it."""
        if not self._check_lock.acquire(blocking=False):
            return "a check is already running"

        def work():
            try:
                log.info("%s", format_report(run_checks(self, BASE)))
            except Exception as e:
                log.warning("/check failed: %s", e)
            finally:
                self._check_lock.release()

        threading.Thread(target=work, name="check", daemon=True).start()
        return "checking (this can take up to 20 seconds; the report appears in the log)..."

    def detach_command(self, by: str | None) -> str:
        """/detach: the same as Ctrl-B then d. Leaves tmux and keeps Bob running."""
        if by is not None:
            return "/detach only works in the tmux console Bob was started in (in bob-console, /detach or Ctrl-C leaves)"
        if not os.environ.get("TMUX"):
            return "Bob isn't running inside tmux, so there is nothing to detach from (use /quit to stop him)"
        import subprocess
        try:
            name = subprocess.run(["tmux", "display-message", "-p", "#{session_name}"], capture_output=True,
                                  text=True, timeout=3).stdout.strip()
            done = subprocess.run(["tmux", "detach-client", "-s", name] if name else ["tmux", "detach-client"],
                                  capture_output=True, text=True, timeout=3)
        except (OSError, subprocess.SubprocessError) as e:
            return f"couldn't run tmux: {e}"
        return "" if done.returncode == 0 else f"tmux said: {done.stderr.strip() or done.returncode}"

    def shutdown_command(self, words: list[str], by: str | None, role: str) -> str:
        """/shutdown, then /shutdown confirm: power the Pi off. Two steps, by the same person."""
        if not self.power.allows(role):
            return "powering the Pi off from here isn't allowed for your kind of user ([power] in config.toml)"
        who = by or "the console"
        if words[:1] == ["cancel"]:
            return self.power.cancel(who)
        if words[:1] != ["confirm"]:
            return self.power.request(who)
        ok, message = self.power.confirm(who)
        if not ok:
            return message
        log.warning("SHUTDOWN: %s is powering the Pi off", who)
        self.timeline.record("power", action="shutdown", by=by or "console")

        def goodbye():
            try:
                self.audio.say("Shutting down now. Goodbye!")
            finally:
                self.quit.set()           # main() shuts Bob down cleanly, then runs the power-off
        self.background(goodbye)
        return "Shutting down: stopping Bob, then powering the Pi off. Unplug and replug the power to start it again."

    def search_command(self, query: str) -> str:
        if not self.index.enabled:
            return "the search index is off: set [index] enabled = true in config.toml"
        if not query.strip():
            return ("usage: /search WORDS [kind:estop] [source:timeline|note|person|radio|log|manual] [since:2h|3d|today|2026-10-16]\n"
                    "  e.g. /search lens covered  |  /search kind:estop since:yesterday  |  /search calibrate source:manual")
        try:
            hits = self.index.search(query, 20)
        except ValueError as e:
            return str(e)
        return "\n".join(self.index.format_hit(h) for h in reversed(hits)) or "nothing found"

    def index_command(self, words: list[str]) -> str:
        if not words:
            return self.index.status() + "  (/search WORDS; /index sync|rebuild|ai on|off)"
        if words[0] == "sync":
            self.index.sync()
            return self.index.status()
        if words[0] == "rebuild":
            return self.index.rebuild()
        if words[0] == "ai" and len(words) == 2 and words[1] in ("on", "off"):
            self.controls.recall_ai = words[1] == "on"
            return f"Bob {'may' if self.controls.recall_ai else 'may NOT'} search his history"
        return "usage: /index | sync | rebuild | ai on|off"

    def tag_min_command(self, words: list[str]) -> str:
        """/tags min: how big (in pixels) a tag must look before Bob believes it. Measured, typed, or reset."""
        cfg = self.cfg.home
        lo, hi = TAG_MIN_LIMITS
        if not words:
            if self.drive.moving:
                return "hold still: he's moving"
            size, text = self.home.measure_tag()
            if size is None:
                return text
            cfg.tag_min_px = self.tuning_extra["tag_min_px"] = max(lo, min(hi, round(size * 0.9)))
            save_tuning(self.cfg.drive, self.calibration, self.tuning_extra)
            return f"{text}\nMinimum set to {cfg.tag_min_px:g} px (90% of that) and saved: tags that look smaller, meaning further away, are ignored."
        if words == ["reset"]:
            cfg.tag_min_px = self.default_tag_min
            self.tuning_extra.pop("tag_min_px", None)
            save_tuning(self.cfg.drive, self.calibration, self.tuning_extra)
            return f"minimum back to {cfg.tag_min_px:g} px (config.toml)"
        try:
            value = float(words[0])
        except ValueError:
            return "usage: /tags min | /tags min <pixels> | /tags min reset"
        cfg.tag_min_px = self.tuning_extra["tag_min_px"] = max(lo, min(hi, value))
        save_tuning(self.cfg.drive, self.calibration, self.tuning_extra)
        return f"minimum set to {cfg.tag_min_px:g} px and saved"

    def _announce_locate(self, session: int) -> None:
        """After a /locate: say the room out loud if it worked. Runs off the console thread."""
        finder = self.home.finder
        outcome = finder.outcome(session, self.cfg.home.tag_search_seconds + 130)
        if outcome and outcome[0]:
            room, _ = self.home.where()
            self.audio.play("chirp")
            self.audio.say(f"I'm in the {room}." if room else "I found a room tag.")
        log.info("LOCATE %s", outcome[1] if outcome else "no result")

    def timeline_command(self, words: list[str]) -> str:
        tl = self.timeline
        if not words:
            return tl.describe() + "  (/timeline on|off, show [n], clear)"
        if words[0] in ("on", "off"):
            tl.enabled = words[0] == "on"
            return "timeline " + ("recording" if tl.enabled else "stopped (existing records are kept; /timeline clear deletes them)")
        if words[0] == "show":
            rows = tl.recent(int(words[1]) if len(words) > 1 and words[1].isdigit() else 20)
            return "\n".join(tl.format(r) for r in rows) or "nothing recorded yet"
        if words[0] == "clear":
            removed = tl.clear()
            self.index.forget("timeline")
            return f"deleted {removed} timeline files and their search records"
        return "usage: /timeline | on | off | show [n] | clear"

    def calibrate_command(self, words: list[str]) -> str:
        what = words[0] if words else "show"
        if what == "show":
            turn = self.calibration.get("turn")
            d = self.cfg.drive
            return (("measured turn rates (deg/s at command speed, speed cap %.2f): " % self.calibration.get("cap", 1.0)
                     + ", ".join(f"{k}: {v:g}" for k, v in turn.items())) if turn else "no turn calibration yet (/calibrate turn)") + \
                f"\ntrims: left {d.left_trim:+.3f}, right {d.right_trim:+.3f}"
        if what == "cancel":
            if self.calibrating:
                self.calibrating.cancel = True
                return "cancelling..."
            return "no calibration is running"
        if what not in ("turn", "straight"):
            return "usage: /calibrate turn | straight | show | cancel   (add 'go' to start)"
        if self.calibrating:
            return "a calibration is already running (/calibrate cancel)"
        if self.drive.estop.is_set():
            return "E-stop active - /clear first"
        if self.controls.auto or self.follower.active:
            return "pause Bob first (/pause): calibration needs the wheels to itself"
        if not self.camera.enabled or self.camera.grab_bgr() is None:
            return "calibration needs the camera (is it on?)"
        d = self.cfg.drive
        plan = ("Bob will spin left and right in short bursts (about 6 spins, each followed by a spin back), "
                "so he needs clear floor around him and a room with some detail in view (not a blank wall)."
                if what == "turn" else
                "Bob will drive forward about half a metre and back, twice, so he needs a metre of clear floor ahead "
                "and a room with some detail in view (not a blank wall).")
        if words[1:2] != ["go"]:
            return f"{plan}\nIt runs at the current speed cap ({self.drive.speed_cap:.2f}). Type '/calibrate {what} go' to start, or press Space to stop."

        def run():
            cal = Calibrator(self.camera, self.drive, self.ranger, self.cfg.camera.fov_deg, say=lambda m: log.info("%s", m))
            self.calibrating = cal
            try:
                if what == "turn":
                    rates = cal.turn()
                    self.calibration = {"turn": rates, "cap": round(self.drive.speed_cap, 3)}
                    self.controls.calibration = self.calibration
                    save_tuning(d, self.calibration, self.tuning_extra)
                    log.info("CALIB done: turn rates (deg/s at command speed): %s - saved, and Bob has been told",
                             ", ".join(f"{k}: {v:g}" for k, v in rates.items()))
                else:
                    res = cal.straight()
                    d.right_trim, d.left_trim = res["right_trim"], res["left_trim"]
                    save_tuning(d, self.calibration, self.tuning_extra)
                    log.info("CALIB done: drift %+.1f deg/s before; trims now left %+.3f, right %+.3f - saved. "
                             "Run /fwd 3 to check it, or /calibrate straight go again to refine",
                             res["drift_before"], d.left_trim, d.right_trim)
            except Exception as e:
                log.error("CALIB failed: %s", e)
            finally:
                self.drive.stop()
                self.calibrating = None

        threading.Thread(target=run, name="calibrate", daemon=True).start()
        return f"calibrating ({what}); watch the log. Space = emergency stop."

    FOLLOW_PHRASES = {"follow me", "come with me", "come here", "come to me", "follow"}
    STOP_PHRASES = {"stop", "halt", "freeze", "stay", "stay there", "stop following", "stop it"}

    def voice_command(self, text: str) -> str | None:
        """Short spoken commands handled right here, without waiting for Claude: 'follow me' and 'stop'.
        Only an utterance that is exactly one of these counts, so ordinary sentences never trigger it."""
        words = " ".join(w for w in re.sub(r"[^\w\s']", " ", text.lower()).split() if w not in ("please", "bob", "now"))
        if words in self.STOP_PHRASES:
            self.follower.stop("told to stop")
            self.drive.stop()
            self.controls.auto = False
            self.controls.stop_gen += 1
            return "stopped (AI paused)"
        if words in self.FOLLOW_PHRASES and self.controls.motion_enabled:
            err = self.follower.start(30.0)
            return "following" if err is None else f"can't follow: {err}"
        return None

    def heard(self, text: str, ptt: bool) -> None:
        """A transcript from the microphone. Push-to-talk gets an answer now, even while paused."""
        log.info("HEARD %s", text)
        if (done := self.voice_command(text)) is not None:
            log.info("VOICE command: %s", done)
            return
        self.controls.post(text)
        if ptt and not self.controls.auto and not self.drive.estop.is_set():
            self.controls.step_once.set()

    def shutdown(self) -> None:
        log.info("Shutting down")
        self.follower.stop("shutting down")
        if self.music:
            self.music.stop()     # puts the music volume back if it was ducked
        if self.gamepad:
            self.gamepad.stop()
        self.listener.stop()
        self.index.stop()
        self.home.stop()
        if self.radio:
            self.radio.stop()
            if self.radio.is_alive():
                self.radio.join(3)
        self.brain.halt.set()
        self.controls.wake.set()
        self.drive.emergency_stop()  # no new moves while the brain winds down
        if self.brain.is_alive():
            self.brain.join(5)
        if self.stream:
            self.stream.stop()
        self.drive.close()
        self.ranger.close()
        self.camera.close()

    # ---- manual driving: for one person, or for everyone attached ------------------------------------------
    @property
    def drive_mode(self) -> bool:
        """Is Bob under manual control (AI paused)? Who is driving is in drive_users."""
        return self._drive_mode

    @drive_mode.setter
    def drive_mode(self, value: bool) -> None:
        if value:                                   # old-style "drive mode on" means the console is driving
            self.join_drive(None)
            return
        with self._drive_lock:
            self._drive_mode = False
            self.drive_users = set()

    def driving_for(self, who: str | None) -> bool:
        """Is this person's keyboard (or controller) driving? `None` is the console Bob runs in."""
        with self._drive_lock:
            return self._drive_mode and (who or "console") in self.drive_users

    def join_drive(self, who: str | None, everyone: bool = False) -> None:
        """Start manual driving for one person, or (everyone) for everyone attached right now."""
        names = {who or "console"}
        if everyone:
            names |= {"console"} | set(getattr(getattr(self, "remote", None), "drivers", lambda: [])())
            if self.gamepad is not None and self.gamepad.connected:
                names.add("gamepad")
        with self._drive_lock:
            self.drive_users = (self.drive_users | names) if self._drive_mode else names
            self._drive_mode = True

    def leave_drive(self, who: str | None) -> None:
        """One person stops driving. Manual control ends when nobody is left driving."""
        with self._drive_lock:
            if not self._drive_mode:
                return
            self.drive_users.discard(who or "console")
            if not self.drive_users:
                self._drive_mode = False

    # ---- overrides ------------------------------------------------------
    def estop(self, source: str = "console") -> None:
        self.follower.stop("emergency stop")
        self.drive.emergency_stop()
        self.controls.auto = False
        self.controls.stop_gen += 1
        self.drive_mode = False
        log.warning("EMERGENCY STOP (%s) - motors locked, AI paused. /clear to release.", source)
        self.timeline.record("estop", source=source)

    def status_line(self) -> str:
        c = self.controls
        if self.drive.estop.is_set():
            mode = "E-STOP"
        elif self.drive_mode:
            mode = "MANUAL DRIVE"
        else:
            mode = "AUTO" if c.auto else "PAUSED"
        return (
            f" BOB  {mode} | {'thinking' if c.busy else 'idle'} | "
            f"motion {'on' if c.motion_enabled else 'OFF'} | "
            f"camera {'on' if self.camera.enabled else 'OFF'} | mic {self.listener.describe()} | "
            + (f"radio {self.radio.state} | " if self.radio else "")
            + ("FOLLOWING | " if self.follower.active else "")
            + ("CALIBRATING | " if self.calibrating else "")
            + ("MUSIC | " if self.music and self.music.playing else "")
            + (f"dist {self.ranger.distance_cm:.0f}cm | " if self.ranger.enabled and self.ranger.distance_cm is not None else "")
            + f"audio {'MUTED' if self.audio.muted else 'on'} | cap {self.drive.speed_cap:.2f} | "
            f"tick {c.ticks} | ${c.cost:.3f} | {self.cfg.brain.model}/{self.cfg.brain.effort}"
            + (" | SIM" if self.drive.sim else "")
        )

    def manual(self, left: float, right: float, seconds: float, blocking: bool = False) -> str:
        if self.drive.estop.is_set():
            return "E-stop active - /clear first"
        now = time.monotonic()
        if now - self._last_manual_event > 2.0:   # a held key sends many moves a second: note the start of each burst
            self._last_manual_event = now
            self.timeline.record("manual_move", left=round(left, 2), right=round(right, 2), seconds=round(seconds, 2))
        if blocking:
            threading.Thread(target=self.drive.move, args=(left, right, seconds), daemon=True).start()
        else:
            self.drive.start(left, right, seconds)
        return f"manual move L={left:+.2f} R={right:+.2f} {seconds:.1f}s"

    def handle(self, line: str, by: str | None = None, role: str = "owner") -> str | None:
        """Run one console line. `by` names the person when it came from the shared console or dashboard;
        `role` says what kind of user they are (owner, operator, viewer or dashboard)."""
        line = line.strip()
        if not line:
            return None
        who = f"[{by}] " if by else ""
        if not line.startswith("/"):
            log.info("YOU  %s%s", who, line)
            self.timeline.record("operator", text=line, by=by)
            self.controls.post(f"{who}{line}")
            return None if self.controls.auto else "queued for Bob - use /ask to get an answer now"

        cmd, _, arg = line[1:].partition(" ")
        arg = arg.strip()
        c = self.controls
        if cmd.lower() not in ("ask", "tell", "timeline", "search", "index"):   # /ask is recorded below; the rest would record themselves
            self.timeline.record("operator_command", cmd=cmd.lower(), arg=arg or None, by=by)
        if cmd.lower() in ("ask", "tell"):
            if not arg:
                return "usage: /ask <message> - Bob answers now, even while paused"
            if self.drive.estop.is_set():
                return "E-stop active - /clear first"
            log.info("YOU  %s%s", who, arg)
            self.timeline.record("operator", text=arg, by=by)
            c.post(f"{who}{arg}")
            if not c.auto:
                c.step_once.set()
            return None

        def secs(default=1.0):
            return float(arg) if arg else default

        match cmd.lower():
            case "help" | "h" | "?":
                return HELP
            case "estop" | "stop":
                self.estop()
            case "clear":
                self.drive.clear_estop()
                return "E-stop released. AI still paused - /resume when ready."
            case "pause" | "hush":
                c.auto = False
                c.stop_gen += 1
                self.follower.stop("paused by the operator")
                self.drive.stop()
                return "AI paused; any thought in progress is cancelled"
            case "think":
                if arg.lower() in ("change", "always"):
                    self.cfg.brain.think_when = "change" if arg.lower() == "change" else "interval"
                    c.wake.set()
                    return ("Bob now thinks only when something changes (or every "
                            f"{self.cfg.brain.idle_max_s:.0f}s)" if arg.lower() == "change"
                            else f"Bob now thinks every {self.cfg.brain.tick_seconds:g}s")
                if arg.lower() == "off":
                    return self.handle("/pause")
                if arg.lower() == "on":
                    return self.handle("/resume")
                return (f"thinking is {'on' if c.auto else 'OFF'}, "
                        f"{'only when something changes' if self.cfg.brain.think_when == 'change' else 'every tick'}"
                        f" ({self.brain.gate.skipped} looks skipped; thresholds: picture {self.cfg.brain.change_percent:g}%, "
                        f"distance {self.cfg.brain.change_distance_cm:g} cm, routine look every {self.cfg.brain.idle_max_s:g}s)"
                        " - /think on|off|change|always")
            case "model":
                if not arg:
                    return f"model: {self.cfg.brain.model} (/model opus|sonnet|haiku)"
                model = MODEL_ALIASES.get(arg.lower(), arg)
                if not model.startswith("claude-"):
                    return "unknown model - try /model opus, sonnet or haiku"
                self.cfg.brain.model = model
                note = "" if model in PRICES else " (cost estimate will use Opus rates)"
                return f"model now {model}, applies from the next thought{note}"
            case "resume" | "go" | "auto":
                if self.drive.estop.is_set():
                    return "E-stop active - /clear first"
                self.drive_mode = False
                c.auto = True
                c.wake.set()
                return "AI running"
            case "step":
                c.step_once.set()
                c.wake.set()
                return "running one tick"
            case "drive":
                if self.drive.estop.is_set():
                    return "E-stop active - /clear first"
                c.auto = False
                everyone = arg.lower() == "all"
                if arg and not everyone:
                    return "usage: /drive (for you) or /drive all (for everyone attached)"
                self.join_drive(by, everyone)
                who = f"{by} is" if by else "you are"
                return ("manual drive for EVERYONE attached right now: " if everyone else f"manual drive ({who} driving; others keep typing): ") + \
                    "WASD/arrows, SPACE stop, Q/ESC exit"
            case "fwd":
                return self.manual(0.6, 0.6, secs(), blocking=True)
            case "back":
                return self.manual(-0.6, -0.6, secs(), blocking=True)
            case "left":
                return self.manual(-0.6, 0.6, secs(0.5), blocking=True)
            case "right":
                return self.manual(0.6, -0.6, secs(0.5), blocking=True)
            case "move":
                l, r, s = (float(x) for x in arg.split())
                return self.manual(l, r, s, blocking=True)
            case "motion":
                c.motion_enabled = arg.lower() != "off"
                return f"AI motion {'enabled' if c.motion_enabled else 'DISABLED'}"
            case "camera" | "cam":
                if arg.lower() not in ("on", "off"):
                    return f"camera is {'on' if self.camera.enabled else 'OFF'} - /camera on|off"
                if not self.camera.set_enabled(arg.lower() == "on"):
                    return "camera failed to start (unplugged? see the log); it stays off"
                if not self.camera.available:
                    return f"camera switched {arg.lower()} (no camera hardware detected)"
                return f"camera {'on' if self.camera.enabled else 'OFF - sensor stopped, no frames go to Claude'}"
            case "trim":
                d = self.cfg.drive
                words = arg.lower().split()
                if not words:
                    return f"trim: left {d.left_trim:+.3f}, right {d.right_trim:+.3f}  (+0.05 = that wheel 5% faster)"
                if words == ["reset"]:
                    d.left_trim = d.right_trim = 0.0
                elif len(words) == 2 and words[0] in ("left", "right"):
                    setattr(d, f"{words[0]}_trim", max(-0.5, min(0.5, float(words[1]))))
                else:
                    return "usage: /trim | /trim left 0.05 | /trim right -0.03 | /trim reset"
                save_tuning(d, self.calibration, self.tuning_extra)
                return f"trim saved: left {d.left_trim:+.3f}, right {d.right_trim:+.3f}"
            case "minduty":
                d = self.cfg.drive
                if not arg:
                    return f"minimum motor duty {d.dc_min_duty:.2f} (raise if a wheel hums without turning)"
                d.dc_min_duty = max(0.0, min(0.9, float(arg)))
                save_tuning(d, self.calibration, self.tuning_extra)
                return f"minimum motor duty {d.dc_min_duty:.2f} saved"
            case "listen" | "mic":
                words = arg.lower().split()
                if not words:
                    return self.listener.status()
                if words[0] in ("on", "off"):
                    return self.listener.set_enabled(words[0] == "on")
                if words[0] == "mode" and len(words) == 2:
                    return self.listener.set_mode(words[1])
                if words[0] == "wake":
                    return self.listener.set_wake(arg.lower().partition("wake")[2])
                if words[0] == "threshold" and len(words) == 2:
                    self.listener.threshold = max(0.002, min(0.5, float(words[1])))
                    return f"speech threshold {self.listener.threshold:.3f} (loudness above this counts as speech)"
                return "usage: /listen | on | off | mode ptt|hands-free | threshold 0.03 | wake ..."
            case "radio":
                if not self.radio:
                    return "radio is off: set [radio] enabled = true in config.toml and BOB_RADIO_SECRET in .env"
                parts = arg.split(None, 1)
                sub_cmd = parts[0].lower() if parts else ""
                rest = parts[1] if len(parts) > 1 else ""
                if not sub_cmd:
                    return self.radio.status() + f"; Bob may send: {'yes' if c.radio_ai else 'NO'}"
                if sub_cmd == "log":
                    return "\n".join(self.radio.format_history(int(rest) if rest else 15)) or "no radio messages yet"
                if sub_cmd == "say":
                    if not rest:
                        return "usage: /radio say <message>"
                    return self.radio.send(rest, source="operator")[1]
                if sub_cmd in ("on", "off"):
                    return self.radio.set_enabled(sub_cmd == "on")
                if sub_cmd == "ai" and rest.lower() in ("on", "off"):
                    c.radio_ai = rest.lower() == "on"
                    return f"Bob {'may' if c.radio_ai else 'may NOT'} send radio messages"
                return "usage: /radio | log [n] | say <text> | on | off | ai on|off"
            case "music":
                return self.music_command(arg.split())
            case "calibrate":
                return self.calibrate_command(arg.lower().split())
            case "follow":
                word = arg.lower().strip()
                if word in ("off", "stop"):
                    self.follower.stop()
                    return "stopping" if self.follower.active else "not following"
                if not c.motion_enabled:
                    return "movement is disabled (/motion on)"
                err = self.follower.start(float(word) if word else 30.0)
                return f"following the nearest face (/follow off to stop; the emergency stop works too)" if err is None \
                    else f"can't follow: {err}"
            case "find":
                word = arg.lower().strip()
                if word in ("off", "stop"):
                    self.follower.stop()
                    return "stopping" if self.follower.active else "not looking"
                if not c.motion_enabled:
                    return "movement is disabled (/motion on)"
                err = self.follower.start(float(word) if word else self.cfg.follow.scan_seconds, mode="find")
                if err is not None:
                    return f"can't look: {err}"
                self.background(self._announce_find, self.follower.session)
                return "turning on the spot to look for a face (/find off to stop; the emergency stop works too)"
            case "check":
                return self.check_command()
            case "timeline":
                return self.timeline_command(arg.lower().split())
            case "where":
                if not self.home.enabled:
                    return "Home Assistant isn't set up ([home] in config.toml), so Bob doesn't track rooms"
                if arg:
                    return self.home.set_manual(arg)
                room, why = self.home.where()
                return f"Bob is in the {room} ({why})" if room else f"Bob doesn't know his room ({why or 'use /where <room>'}). Rooms: {', '.join(self.home.rooms.values())}"
            case "locate":
                word = arg.lower().strip()
                if word in ("off", "stop"):
                    if self.home.finder and self.home.finder.active:
                        self.home.finder.stop()
                        return "stopping"
                    return "not looking"
                if not self.home.enabled:
                    return "Home Assistant isn't set up ([home] in config.toml), so Bob doesn't track rooms"
                if not c.motion_enabled:
                    return "movement is disabled (/motion on)"
                status, text = self.home.locate(float(word) if word else None)
                if status == "started":
                    self.background(self._announce_locate, self.home.finder.session)
                    return text + " (/locate off to stop; the emergency stop works too)"
                return text
            case "tags":
                if not self.home.enabled:
                    return "Home Assistant isn't set up ([home] in config.toml), so Bob doesn't track rooms"
                words = arg.lower().split()
                if words[:1] == ["min"]:
                    return self.tag_min_command(words[1:])
                if words:
                    return "usage: /tags | /tags min | /tags min <pixels> | /tags min reset"
                return self.home.tags_report(self.camera.grab_bgr() if self.camera.enabled else None)
            case "home":
                return self.home_command(arg.lower().split())
            case "access":
                if not self.access.configured:
                    return "no dashboard tokens are set: add BOB_STREAM_TOKEN or TOKEN_NAME lines to .env (manual 07)"
                return self.access.describe()
            case "shutdown":
                return self.shutdown_command(arg.lower().split(), by, role)
            case "who":
                text = self.remote.describe() if getattr(self, "remote", None) else "off"
                return "the shared console is off ([remote] enabled = true)" if text == "off" else text
            case "search":
                return self.search_command(arg)
            case "index":
                return self.index_command(arg.lower().split())
            case "range" | "sensor":
                words = arg.lower().split()
                if not self.ranger.available and not words:
                    return "no distance sensor: set [sensor] enabled = true in config.toml and wire it up (see README)"
                if not words:
                    return f"{self.ranger.describe()} (stops forward moves inside {self.ranger.stop_cm} cm; /range stop N, /range on|off)"
                if words[0] in ("on", "off"):
                    self.ranger.enabled = words[0] == "on"
                    return f"obstacle reflex {'on' if self.ranger.enabled else 'OFF (the wheels will NOT stop for obstacles)'}"
                if words[0] == "stop" and len(words) == 2:
                    self.ranger.stop_cm = max(3, min(100, int(float(words[1]))))
                    return f"forward moves now stop inside {self.ranger.stop_cm} cm"
                return "usage: /range | on | off | stop <cm>"
            case "talk":
                return self.listener.ptt_toggle()
            case "speed":
                self.drive.speed_cap = max(0.0, min(1.0, float(arg)))
                return f"speed cap {self.drive.speed_cap:.2f}"
            case "say":
                if not arg:
                    return "usage: /say <text>"
                self.background(self.audio.say, arg)
                return f"saying: {arg}"
            case "sound":
                if arg not in SOUNDS:
                    return f"unknown sound - try: {' '.join(SOUNDS)}"
                self.background(self.audio.play, arg)
                return f"playing {arg}"
            case "mute" | "unmute":
                self.audio.muted = cmd == "mute"
                return "audio muted" if self.audio.muted else "audio on"
            case "goal":
                if arg:
                    c.goal = arg
                    c.wake.set()
                return f"goal: {c.goal}"
            case "snap":
                if not self.camera.enabled:
                    return "camera is off - /camera on first"
                jpeg = self.camera.capture_jpeg()
                if jpeg is None:
                    return "camera unavailable"
                path = BASE / "captures" / f"{datetime.now():%Y%m%d-%H%M%S}.jpg"
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(jpeg)
                return f"saved {path.relative_to(BASE)}"
            case "notes":
                return "\n".join(f"  - {n}" for n in self.memory.notes) or "no notes"
            case "people":
                words = arg.split(None, 1)
                if words and words[0].lower() == "forget" and len(words) == 2:
                    done = self.people.forget(words[1])
                    self.index.sync()
                    return f"forgot {words[1]}" if done else f"I don't know a {words[1]}"
                if words and words[0].lower() == "clear":
                    for n in list(self.people.people):
                        self.people.forget(n)
                    self.index.sync()
                    return "forgot everyone"
                return "\n".join(self.people.lines()) or "Bob doesn't know anybody yet (/people forget <name>, /people clear)"
            case "forget":
                self.memory.clear()
                self.index.sync()
                return "notes wiped"
            case "effort":
                if arg not in ("low", "medium", "high", "xhigh", "max"):
                    return "effort must be low|medium|high|xhigh|max"
                self.cfg.brain.effort = arg
                return f"effort {arg}"
            case "detach":
                return self.detach_command(by)
            case "quit" | "exit":
                self.quit.set()
            case _:
                return f"unknown command /{cmd} - try /help"
        return None


def run_headless(ctrl: Controller) -> None:
    def reader():
        for line in sys.stdin:
            try:
                out = ctrl.handle(line)
            except Exception as e:
                out = f"error: {e}"
            if out:
                print(out, flush=True)
        # stdin closed (e.g. under systemd): keep running until signalled
    threading.Thread(target=reader, daemon=True).start()
    ctrl.quit.wait()


def main() -> None:
    ap = argparse.ArgumentParser(description="Bob the Claude-powered robot")
    ap.add_argument("--config", type=Path, default=BASE / "config.toml")
    ap.add_argument("--sim", action="store_true", help="simulate all hardware")
    ap.add_argument("--paused", action="store_true", help="start with the AI paused")
    ap.add_argument("--headless", action="store_true", help="no TUI; log to stdout")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    load_env(BASE / ".env")
    cfg = config.load(args.config)

    (BASE / "logs").mkdir(exist_ok=True)
    log.setLevel(logging.DEBUG if args.debug else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-5s %(message)s", "%H:%M:%S")
    fh = RotatingFileHandler(BASE / "logs" / "bob.log", maxBytes=2_000_000, backupCount=5)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s %(name)s: %(message)s"))
    log.addHandler(fh)
    for noisy in ("httpx", "httpcore", "anthropic", "picamera2", "faster_whisper", "huggingface_hub", "hf_xet"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    from console import LogBuffer
    logbuf = LogBuffer()          # the console and the phone dashboard both read recent lines from here
    logbuf.setFormatter(fmt)
    log.addHandler(logbuf)
    if args.headless:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        log.addHandler(sh)

    ctrl = Controller(cfg, sim=args.sim, paused=args.paused)
    from remote import RemoteConsole
    ctrl.remote = RemoteConsole(cfg.remote, ctrl, logbuf)
    signal.signal(signal.SIGTERM, lambda *_: ctrl.quit.set())
    signal.signal(signal.SIGHUP, lambda *_: ctrl.quit.set())
    if ctrl.stream:
        ctrl.stream.attach(ctrl, logbuf)
    ctrl.start()
    ctrl.remote.start()
    try:
        if args.headless:
            run_headless(ctrl)
        else:
            from console import run_console
            run_console(ctrl, logbuf)
    except KeyboardInterrupt:
        pass
    finally:
        ctrl.remote.stop()
        ctrl.shutdown()
        if ctrl.power.requested:                  # a confirmed /shutdown: Bob is stopped cleanly, now power off
            ok, message = ctrl.power.execute()
            log.warning("%s", message)
            print(message, file=sys.stderr)


if __name__ == "__main__":
    main()
