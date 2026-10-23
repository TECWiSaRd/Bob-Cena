"""Home Assistant: Bob can turn on or off the lights in the room he is in, and nothing else.

What he can do is deliberately small, and the limits live here in code where Claude can't change them:
  - only `light.*` entities, only in rooms the operator lists in config.toml, and only the room Bob is in;
  - he must know which room that is (the operator's /where, or a room sensor in Home Assistant);
  - a rate limit, a pause between changes to the same room, and quiet hours when he may not turn lights ON;
  - the access token is read from the environment and never shown to Claude. Light names are never shown to
    him either, only counts, so nothing a device is called can steer him.
Only the standard library is used (urllib), so there is nothing to install.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime

log = logging.getLogger("bob.home")

ENTITY_ID = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
UNKNOWN_STATES = {"", "unknown", "unavailable", "none", "not_home", "away"}


def slug(text: str) -> str:
    """A room name or Home Assistant area ID in one comparable form. Apostrophes are dropped, as Home Assistant
    does when it makes an area ID, so "Adam's Room" and adams_room are the same room."""
    return re.sub(r"[^a-z0-9]+", "_", re.sub(r"['\u2019\u2018`]", "", str(text).lower())).strip("_")


def parse_clock(text: str) -> tuple[int, int] | None:
    """'22:30' -> (22, 30). An empty text means 'not set'. Anything else raises ValueError."""
    if not text.strip():
        return None
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", text.strip())
    if not m:
        raise ValueError(f"'{text}' isn't a time like 22:30")
    return int(m.group(1)), int(m.group(2))


class HomeError(Exception):
    pass


class HomeAssistant:
    """The few Home Assistant REST calls Bob uses."""

    def __init__(self, url: str, token: str, timeout: float = 5.0):
        if not url.startswith(("http://", "https://")):
            raise ValueError("[home] url must start with http:// or https://")
        self.url, self._token, self.timeout = url.rstrip("/"), token, timeout

    def _call(self, method: str, path: str, body: dict | None = None):
        req = urllib.request.Request(
            self.url + path, method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise HomeError("Home Assistant rejected the access token (HA_TOKEN)")
            raise HomeError(f"Home Assistant said {e.code} for {path.split('/')[2] if path.count('/') > 1 else path}")
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise HomeError(f"can't reach Home Assistant at {self.url} ({getattr(e, 'reason', e)})")
        try:
            return json.loads(raw) if raw else None
        except ValueError:
            return raw.decode("utf-8", "replace")

    def ping(self) -> str:
        data = self._call("GET", "/api/")
        return data.get("message", "ok") if isinstance(data, dict) else "ok"

    def state(self, entity_id: str) -> dict:
        if not ENTITY_ID.match(entity_id):
            raise HomeError("bad entity id")
        return self._call("GET", f"/api/states/{entity_id}")

    def template(self, text: str) -> str:
        data = self._call("POST", "/api/template", {"template": text})
        return data if isinstance(data, str) else json.dumps(data)

    def call(self, domain: str, service: str, data: dict) -> None:
        if not (re.fullmatch(r"[a-z_]+", domain) and re.fullmatch(r"[a-z_]+", service)):
            raise HomeError("bad service name")
        self._call("POST", f"/api/services/{domain}/{service}", data)


class Home:
    def __init__(self, cfg, token: str, clock=time.time, now=datetime.now, client: HomeAssistant | None = None):
        self.cfg, self._clock, self._now = cfg, clock, now
        self.problem = ""
        self.enabled = False
        self.client = client
        self.on_event = None                  # callback(**fields) for the timeline
        self.manual_room: str | None = None   # set by the operator's /where
        self.rooms = {slug(r): r for r in cfg.rooms}
        self.quiet: tuple = (None, None)
        self.tracker = None                   # TagTracker, when room tags are configured
        self.scanner = None
        self.finder = None                    # TagFinder: turns to look for a tag
        self.goer = None                      # TagGoer: drives to a room's tag
        self.paths: dict[str, list[int]] = {}
        self.moved = lambda: 0.0              # the drive's moved_total, set by the controller
        self.wifi_reader = lambda: None       # the current Wi-Fi network name, set by the controller
        self._lock = threading.Lock()
        self._recent: deque[float] = deque()
        self._last_change: dict[str, float] = {}
        self._lights: dict[str, tuple[float, list[str]]] = {}
        self._loc: tuple[float, str | None, str] = (0.0, None, "")
        if not cfg.enabled:
            return
        try:
            self.quiet = (parse_clock(cfg.quiet_start), parse_clock(cfg.quiet_end))
            self.tag_rooms = {}
            for key, room in cfg.tags.items():
                if not str(key).isdigit() or not isinstance(room, str):
                    raise ValueError(f"[home] tags: '{key}' should be a tag number, set to a room name")
                self.tag_rooms[int(key)] = room
            for room, ids in cfg.paths.items():
                if (not isinstance(ids, list) or not ids or not all(isinstance(i, int) and i in self.tag_rooms for i in ids)):
                    raise ValueError(f"[home] paths: '{room}' should be a list of tag numbers that are listed under tags")
                self.paths[slug(room)] = list(ids)
            if not self.rooms:
                raise ValueError("[home] rooms is empty: list the Home Assistant areas Bob may control")
            if client is None:
                if not token:
                    raise ValueError("set HA_TOKEN in .env to a Home Assistant long-lived access token")
                self.client = HomeAssistant(cfg.url, token)
            self.enabled = True
        except ValueError as e:
            self.problem = str(e)
            log.error("Home Assistant disabled: %s", e)

    # ---- is there a Home Assistant at this house? ---------------------------------------------------------------
    def active(self) -> bool:
        """Is Home Assistant in use right now? With [home] wifi set, only while Bob is on one of those networks, so at
        a friend's house (no Home Assistant) he makes no calls, takes no slow lookups and logs no warnings."""
        if not self.enabled:
            return False
        if not self.cfg.wifi:
            return True
        try:
            return self.wifi_reader() in self.cfg.wifi
        except Exception:
            return False

    def inactive_reason(self) -> str:
        try:
            here = self.wifi_reader()
        except Exception:
            here = None
        return (f"Bob is on Wi-Fi '{here}'" if here else "Bob can't tell which Wi-Fi he is on") + \
            f", and Home Assistant is only used on: {', '.join(self.cfg.wifi)}"

    # ---- where is Bob? ----------------------------------------------------------------------------------
    def attach_camera(self, camera, drive) -> None:
        """Start looking for room tags (if any are configured) using Bob's camera. `drive` supplies how far he has gone."""
        from tags import TagFinder, TagGoer, TagScanner, TagTracker
        self.moved = drive.moved_total
        if self.enabled and self.cfg.tags and self.scanner is None:
            self.tracker = TagTracker(self.cfg)
            self.scanner = TagScanner(self.cfg, self.tracker, camera, drive.moved_total)
            self.scanner.start()
            self.finder = TagFinder(self.cfg, self.tracker, lambda: self.scanner.detector, camera, drive)
            self.goer = TagGoer(self.cfg, self.tracker, lambda: self.scanner.detector, camera, drive)

    def stop(self) -> None:
        if self.finder and self.finder.active:
            self.finder.stop("shutting down")
        if self.goer and self.goer.active:
            self.goer.stop("shutting down")
        if self.scanner:
            self.scanner.stop()

    def locate(self, seconds: float | None = None, allowed=lambda: True) -> tuple[str, str]:
        """Turn on the spot to look for a room tag. Returns (status, message): status is 'started', 'known' or 'error'."""
        if not self.enabled or self.finder is None:
            return "error", "room tags aren't set up: add them under [home] tags in config.toml (manual 19)"
        if not self.active():
            return "error", "there are no smart lights at this house, so there is no need to find your room"
        room, why = self.where()
        if room:
            return "known", f"You already know your room: the {room} ({why}). No need to look."
        err = self.finder.start(seconds if seconds is not None else self.cfg.tag_search_seconds, allowed)
        if err:
            return "error", f"can't look for a room tag: {err}"
        if self.on_event:
            self.on_event(action="locate", note="started")
        return "started", "turning on the spot to look for a room tag"

    def destinations(self) -> list[str]:
        return sorted(set(self.tag_rooms.values())) if self.enabled else []

    def goto(self, room_text: str, seconds: float | None = None, allowed=lambda: True) -> tuple[str, str]:
        """Drive to a room's tag. Returns (status, message): 'started', 'known' (already there) or 'error'."""
        if not self.enabled or self.goer is None:
            return "error", "room tags aren't set up: add them under [home] tags in config.toml (manual 19)"
        if not self.active():
            return "error", "there are no room tags to follow at this house"
        key = slug(room_text)
        room = next((r for r in self.destinations() if slug(r) == key), None)
        if room is None:
            return "error", f"I don't know a room called '{room_text}'. Rooms with a tag: {', '.join(self.destinations()) or 'none'}"
        here, _ = self.where()
        if here and slug(here) == key:
            return "known", f"You are already in the {room}."
        hops = self.paths.get(key) or sorted(i for i, r in self.tag_rooms.items() if slug(r) == key)[:1]
        err = self.goer.start(room, hops, seconds if seconds is not None else self.cfg.goto_seconds, allowed)
        if err:
            return "error", f"can't go to the {room}: {err}"
        if self.on_event:
            self.on_event(action="goto", note=f"started: {room}")
        return "started", f"heading for the {room}"

    def goto_result(self) -> str:
        room, _ = self.where()
        text = self.goer.result if self.goer else ""
        return f"{text}. " + (f"Now you are in the {room}." if room else "Your room is still unknown.")

    def locate_result(self) -> str:
        room, why = self.where()
        text = self.finder.result if self.finder else ""
        return f"{text}. " + (f"Now you are in the {room}." if room else "You still don't know your room.")

    def _tag_room(self) -> tuple[str | None, str]:
        """(room, why). A room from a room tag, or (None, the reason there isn't one)."""
        if self.tracker is None:
            return None, ""
        tag, why = self.tracker.current(self.moved())
        if tag is None:
            return None, why
        name = self.tag_rooms.get(tag)
        if name is None:
            return None, f"room tag {tag} isn't listed under [home] tags"
        if slug(name) not in self.rooms:
            return None, f"room tag {tag} is for the {name}, which Bob isn't allowed to control"
        return self.rooms[slug(name)], f"seen on room tag {tag}"

    def where(self) -> tuple[str | None, str]:
        """(the configured room name or None, where that came from)."""
        if not self.active():
            return None, "Home Assistant isn't used on this network"
        if self.manual_room:
            return self.rooms.get(self.manual_room), "set by the operator"
        room, tag_why = self._tag_room()
        if room:
            return room, tag_why
        if not self.cfg.location_entity:
            return None, tag_why
        now = self._clock()
        if now - self._loc[0] < 5.0:
            return self._loc[1], self._loc[2]
        room, why = None, ""
        try:
            state = str(self.client.state(self.cfg.location_entity).get("state", "")).strip()
            if state.lower() in UNKNOWN_STATES:
                why = f"the room sensor says '{state or 'nothing'}'"
            elif slug(state) in self.rooms:
                room, why = self.rooms[slug(state)], "from Home Assistant"
            else:
                why = "the room sensor names a room Bob isn't allowed to control"
            if room is None and tag_why:
                why = f"{tag_why}; {why}"
        except HomeError as e:
            why = str(e)
        self._loc = (now, room, why)
        return room, why

    def tags_report(self, frame) -> str:
        """What the camera sees right now, for /tags. Helps decide where to put a tag."""
        if not self.cfg.tags:
            return "no room tags are set up: add them under [home] tags in config.toml (manual 19)"
        scanner = self.scanner
        if scanner is None or scanner.detector is None:
            return scanner.problem if scanner and scanner.problem else "the tag scanner isn't running"
        lines = []
        if frame is None:
            lines.append("no camera picture (is the camera on?)")
        else:
            seen = scanner.detector.detect(frame)
            for t in sorted(seen, key=lambda t: -t.size_px):
                name = self.tag_rooms.get(t.id)
                verdict = ("ignored: too small, he isn't close enough" if t.size_px < self.cfg.tag_min_px
                           else f"counts: the {name}" if name else "counts, but it isn't listed under [home] tags")
                lines.append(f"  tag {t.id}: {t.size_px:.0f} px wide ({verdict})")
            if not seen:
                lines.append("  no tags in view")
        room, why = self.where()
        lines.append(f"  Bob's room now: {room} ({why})" if room else f"  Bob's room now: unknown ({why or 'nothing to go on'})")
        return "\n".join(lines)

    def measure_tag(self, looks: int = 12, gap: float = 0.12, sleep=time.sleep) -> tuple[float | None, str]:
        """Watch the tag in front of the camera for a moment. Returns (typical width in pixels, a message about it)."""
        scanner = self.scanner
        if scanner is None or scanner.detector is None:
            return None, scanner.problem if scanner and scanner.problem else "the tag scanner isn't running (are room tags set up?)"
        seen: list[tuple[int, float]] = []
        for _ in range(looks):
            frame = scanner.camera.grab_bgr()
            if frame is None:
                return None, "no camera picture (is the camera on?)"
            tags = scanner.detector.detect(frame)
            if tags:
                best = max(tags, key=lambda t: t.size_px)
                seen.append((best.id, best.size_px))
            sleep(gap)
        if len(seen) < looks // 2:
            return None, (f"saw a tag in only {len(seen)} of {looks} looks. Face him straight at one tag, hold him still, "
                          "and make sure it is well lit")
        ids = [i for i, _ in seen]
        tag = max(set(ids), key=ids.count)
        sizes = sorted(s for i, s in seen if i == tag)
        if len(sizes) < looks // 2:
            return None, "he keeps seeing different tags: aim him at just one"
        median = sizes[len(sizes) // 2]
        return median, (f"Measured tag {tag}: {median:.0f} px wide (median of {len(sizes)} looks, "
                        f"range {sizes[0]:.0f} to {sizes[-1]:.0f}).")

    def set_manual(self, text: str) -> str:
        text = text.strip()
        if text.lower() in ("", "clear", "off", "auto"):
            self.manual_room = None
            self.manual_room = None
            return "location back to automatic" + (" (room tags and the Home Assistant sensor)" if self.cfg.tags or self.cfg.location_entity else " (none set, so Bob doesn't know where he is)")
        if slug(text) not in self.rooms:
            return f"'{text}' isn't one of Bob's rooms: {', '.join(self.rooms.values())}"
        self.manual_room = slug(text)
        return f"OK: Bob is in the {self.rooms[self.manual_room]}"

    # ---- lights -------------------------------------------------------------------------------------------
    def _room_lights(self, room: str) -> list[str]:
        cached = self._lights.get(room)
        if cached and self._clock() - cached[0] < 60:
            return cached[1]
        # The area name goes inside a quoted string in a template: escape it so it can only ever be text
        # (an apostrophe in "Adam's Room" must still find that room, and nothing in a name can become code).
        safe = "".join(c for c in room if c.isprintable()).replace("\\", "\\\\").replace("'", "\\'")
        out = self.client.template(
            "{{ area_entities('" + safe + "') | select('match', 'light[.]') | list | tojson }}")
        try:
            found = [e for e in json.loads(out) if isinstance(e, str) and ENTITY_ID.match(e) and e.startswith("light.")]
        except ValueError:
            raise HomeError("Home Assistant didn't understand the area name")
        self._lights[room] = (self._clock(), found)
        return found

    def quiet_now(self) -> bool:
        start, end = self.quiet
        if start is None or end is None:
            return False
        t = (self._now().hour, self._now().minute)
        return (start <= t < end) if start <= end else (t >= start or t < end)

    def summary(self, room: str) -> str:
        lights = self._room_lights(room)
        if not lights:
            return f"There are no lights in the {room} that Bob can control."
        on = sum(1 for e in lights if str(self.client.state(e).get("state")) == "on")
        return f"{len(lights)} light{'s' * (len(lights) != 1)} in the {room}: {on} on, {len(lights) - on} off."

    def act(self, action: str, brightness_pct: int | None = None, operator: bool = False) -> tuple[str, bool]:
        """Run a light action in Bob's room. Returns (message, is_error)."""
        if not self.enabled:
            return "Home Assistant isn't set up.", True
        if not self.active():
            return "There are no smart lights to control at this house.", True
        action = action.lower()
        if action not in ("status", "on", "off"):
            return "action must be status, on or off", True
        with self._lock:
            try:
                room, why = self.where()
                if room is None:
                    return ("I don't know which room I'm in" + (f" ({why})" if why else "")
                            + ", so I won't touch any lights. The operator can tell me with /where."), True
                if action == "status":
                    return self.summary(room), False
                now = self._clock()
                if not operator:
                    if action == "on" and self.quiet_now():
                        return (f"Quiet hours ({self.cfg.quiet_start}-{self.cfg.quiet_end}): "
                                "I'm not allowed to turn lights on right now."), True
                    while self._recent and now - self._recent[0] > 60:
                        self._recent.popleft()
                    if len(self._recent) >= self.cfg.max_per_minute:
                        return "Too many light changes this minute. Wait a bit.", True
                    wait = self.cfg.cooldown_s - (now - self._last_change.get(slug(room), -1e9))
                    if wait > 0:
                        return f"I changed the {room} lights {self.cfg.cooldown_s - wait:.0f}s ago; wait {wait:.0f}s before changing them again.", True
                lights = self._room_lights(room)
                if not lights:
                    return f"There are no lights in the {room} that I can control.", True
                data: dict = {"entity_id": lights}
                if action == "on" and brightness_pct is not None:
                    data["brightness_pct"] = max(1, min(100, int(brightness_pct)))
                self.client.call("light", "turn_on" if action == "on" else "turn_off", data)
                self._recent.append(now)
                self._last_change[slug(room)] = now
                if self.on_event:
                    self.on_event(action=action, room=room, lights=len(lights), by="operator" if operator else "claude",
                                  brightness_pct=data.get("brightness_pct"))
                return f"Turned the {room} lights {action} ({len(lights)} light{'s' * (len(lights) != 1)}).", False
            except (HomeError, ValueError, TypeError) as e:
                return f"Home Assistant problem: {e}", True

    # ---- reports ----------------------------------------------------------------------------------------
    def status_lines(self, brightness: float | None) -> list[str]:
        """Lines for Claude's status report. Never contains device names or the token."""
        if not self.active():
            return []
        room, why = self.where()
        lines = [f"Room: {room} ({why})." if room else f"Room: unknown{f' ({why})' if why else ''}. "
                 "You can't use the lights until you know where you are."
                 + (" You can turn on the spot and look for a room tag with the find_my_room tool, or the operator can tell you."
                    if self.finder is not None else " The operator can tell you.")]
        if brightness is not None:
            label = "dark" if brightness < self.cfg.dark_below else "dim" if brightness < self.cfg.bright_above else "bright"
            lines.append(f"Light level at your camera: {label} (brightness {brightness:.0f} of 255).")
        if self.quiet_now():
            lines.append(f"Quiet hours until {self.cfg.quiet_end}: you may not turn lights on (off is fine).")
        return lines

    def check(self) -> tuple[str, str]:
        """(level, detail) for /check."""
        if not self.cfg.enabled:
            return "off", "not enabled in config.toml"
        if not self.enabled:
            return "FAIL", self.problem
        if not self.active():
            return "off", f"not used on this network ({self.inactive_reason()})"
        try:
            self.client.ping()
        except HomeError as e:
            return "FAIL", str(e)
        if self.scanner is not None and self.scanner.problem:
            return "WARN", f"reachable, but {self.scanner.problem}"
        room, why = self.where()
        if room:
            return "ok", f"reachable; Bob is in the {room} ({why})"
        return "WARN", f"reachable, but Bob doesn't know his room ({why or 'no room sensor set; use /where'})"
