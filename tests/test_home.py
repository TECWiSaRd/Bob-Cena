"""Checks for the Home Assistant lights, against a small fake Home Assistant. Run:  python3 -m unittest discover -s tests"""
import json
import os
import re
import sys
import threading
import unittest
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from home import Home, HomeAssistant, HomeError, parse_clock, slug  # noqa: E402

TOKEN = "super-secret-token-123"


class FakeHA:
    """Just enough of Home Assistant's REST API: states, area templates and light services."""

    def __init__(self):
        self.states = {
            "light.kitchen_ceiling": "off", "light.kitchen_strip": "on", "light.living_lamp": "off",
            "switch.kitchen_kettle": "off", "lock.front_door": "locked", "sensor.bob_area": "Kitchen",
        }
        self.areas = {"kitchen": ["light.kitchen_ceiling", "light.kitchen_strip", "switch.kitchen_kettle", "lock.front_door"],
                      "living room": ["light.living_lamp"], "bedroom": []}
        self.calls = []
        self.fail = False
        ha = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, code, obj, text=False):
                body = (obj if text else json.dumps(obj)).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _auth(self):
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    self._reply(401, {"message": "no"})
                    return False
                if ha.fail:
                    self._reply(500, {"message": "broken"})
                    return False
                return True

            def do_GET(self):
                if not self._auth():
                    return
                if self.path == "/api/":
                    return self._reply(200, {"message": "API running."})
                m = re.fullmatch(r"/api/states/(.+)", self.path)
                if m and m.group(1) in ha.states:
                    return self._reply(200, {"entity_id": m.group(1), "state": ha.states[m.group(1)]})
                self._reply(404, {"message": "not found"})

            def do_POST(self):
                if not self._auth():
                    return
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
                if self.path == "/api/template":
                    area = re.search(r"area_entities\('([^']*)'\)", body["template"]).group(1).lower()
                    ents = [e for e in ha.areas.get(area, []) if re.match("light[.]", e)]
                    return self._reply(200, json.dumps(ents), text=True)
                m = re.fullmatch(r"/api/services/light/(turn_on|turn_off)", self.path)
                if m:
                    ha.calls.append((m.group(1), body))
                    for e in body["entity_id"]:
                        ha.states[e] = "on" if m.group(1) == "turn_on" else "off"
                    return self._reply(200, [])
                self._reply(404, {"message": "no such service"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, args=(0.02,), daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


def cfg_for(url, **kw):
    base = dict(enabled=True, url=url, rooms=["Kitchen", "Living Room"], location_entity="sensor.bob_area",
                quiet_start="22:00", quiet_end="07:00", cooldown_s=30.0)
    base.update(kw)
    return config.HomeConfig(**base)


class HomeTests(unittest.TestCase):
    def setUp(self):
        self.ha = FakeHA()
        self.addCleanup(self.ha.stop)
        self.clock = Clock()
        self.hour = 14

    def home(self, **kw):
        return Home(cfg_for(self.ha.url, **kw), TOKEN, clock=self.clock, now=lambda: datetime(2026, 10, 18, self.hour, 0))

    # ---- location -----------------------------------------------------------------------------------------
    def test_room_comes_from_the_ha_sensor(self):
        room, why = self.home().where()
        self.assertEqual(room, "Kitchen")
        self.assertIn("Home Assistant", why)

    def test_room_names_match_loosely(self):
        self.ha.states["sensor.bob_area"] = "living  room"
        self.assertEqual(self.home().where()[0], "Living Room")

    def test_unknown_or_unlisted_rooms_mean_unknown(self):
        for state in ("unknown", "unavailable", "not_home", "Bedroom", ""):
            self.ha.states["sensor.bob_area"] = state
            self.assertIsNone(self.home().where()[0], state)

    def test_operator_override_and_clear(self):
        h = self.home()
        self.assertIn("OK", h.set_manual("living room"))
        self.assertEqual(h.where()[0], "Living Room")
        self.assertIn("isn't one of", h.set_manual("garage"))
        self.assertEqual(h.where()[0], "Living Room")        # a refused room changes nothing
        h.set_manual("clear")
        self.assertEqual(h.where()[0], "Kitchen")

    def test_no_sensor_and_no_override_means_unknown(self):
        h = self.home(location_entity="")
        self.assertIsNone(h.where()[0])
        text, err = h.act("on")
        self.assertTrue(err)
        self.assertIn("don't know which room", text)
        self.assertEqual(self.ha.calls, [])

    # ---- lights -------------------------------------------------------------------------------------------
    def test_status_counts_lights_without_naming_them(self):
        text, err = self.home().act("status")
        self.assertFalse(err)
        self.assertEqual(text, "2 lights in the Kitchen: 1 on, 1 off.")
        self.assertNotIn("ceiling", text)

    def test_on_switches_only_this_rooms_lights(self):
        text, err = self.home().act("on")
        self.assertFalse(err)
        (service, body), = self.ha.calls
        self.assertEqual(service, "turn_on")
        self.assertEqual(sorted(body["entity_id"]), ["light.kitchen_ceiling", "light.kitchen_strip"])
        self.assertEqual(self.ha.states["light.living_lamp"], "off")          # another room: untouched
        self.assertEqual(self.ha.states["lock.front_door"], "locked")         # not a light: untouched
        self.assertEqual(self.ha.states["switch.kitchen_kettle"], "off")
        self.assertIn("Turned the Kitchen lights on", text)

    def test_brightness_is_clamped(self):
        self.home().act("on", 500)
        self.assertEqual(self.ha.calls[-1][1]["brightness_pct"], 100)
        self.clock.t += 100
        self.home().act("on", -5)
        self.assertEqual(self.ha.calls[-1][1]["brightness_pct"], 1)

    def test_off(self):
        self.home().act("off")
        self.assertEqual(self.ha.calls[-1][0], "turn_off")

    def test_bad_actions_are_refused(self):
        text, err = self.home().act("explode")
        self.assertTrue(err)
        self.assertEqual(self.ha.calls, [])

    def test_a_room_with_no_lights(self):
        self.ha.states["sensor.bob_area"] = "Living Room"
        self.ha.areas["living room"] = []
        text, err = self.home().act("on")
        self.assertTrue(err)
        self.assertEqual(self.ha.calls, [])

    # ---- limits -------------------------------------------------------------------------------------------
    def test_quiet_hours_block_on_but_not_off(self):
        for hour in (22, 23, 0, 3, 6):
            self.hour = hour
            h = self.home()
            text, err = h.act("on")
            self.assertTrue(err, hour)
            self.assertIn("Quiet hours", text)
            self.assertFalse(h.act("off")[1], hour)
            self.clock.t += 100
        self.hour = 7
        self.assertFalse(self.home().act("on")[1])

    def test_operator_ignores_quiet_hours_limits_and_cooldown(self):
        self.hour = 23
        h = self.home()
        for _ in range(10):
            self.assertFalse(h.act("on", operator=True)[1])

    def test_cooldown_stops_flicker(self):
        h = self.home()
        self.assertFalse(h.act("on")[1])
        text, err = h.act("off")
        self.assertTrue(err)
        self.assertIn("wait", text)
        self.clock.t += 31
        self.assertFalse(h.act("off")[1])

    def test_rate_limit(self):
        h = self.home(cooldown_s=0.0, max_per_minute=3)
        results = []
        for _ in range(5):
            results.append(h.act("on")[1])
            self.clock.t += 1
        self.assertEqual(results, [False, False, False, True, True])
        self.clock.t += 70
        self.assertFalse(h.act("on")[1])

    # ---- failures -----------------------------------------------------------------------------------------
    def test_wrong_token_is_explained_without_leaking_it(self):
        h = Home(cfg_for(self.ha.url), "wrong-token", clock=self.clock)
        text, err = h.act("on")
        self.assertTrue(err)
        self.assertIn("HA_TOKEN", text)
        self.assertNotIn("wrong-token", text)

    def test_home_assistant_down_does_not_raise(self):
        self.ha.stop()
        h = Home(cfg_for(self.ha.url), TOKEN, clock=self.clock)
        text, err = h.act("on")
        self.assertTrue(err)
        self.assertIn("can't reach", text)
        self.assertEqual(h.check()[0], "FAIL")
        self.ha.server = type("S", (), {"shutdown": lambda s: None, "server_close": lambda s: None})()

    def test_server_error_does_not_raise(self):
        self.ha.fail = True
        text, err = self.home().act("on")
        self.assertTrue(err)

    def test_config_problems_disable_it(self):
        self.assertFalse(Home(cfg_for(self.ha.url), "").enabled)                      # no token
        self.assertFalse(Home(cfg_for(self.ha.url, rooms=[]), TOKEN).enabled)         # no rooms
        self.assertFalse(Home(cfg_for(self.ha.url, quiet_start="25:99"), TOKEN).enabled)
        self.assertFalse(Home(cfg_for("ftp://example.com"), TOKEN).enabled)
        self.assertFalse(Home(config.HomeConfig(), TOKEN).enabled)                    # not turned on
        self.assertIn("HA_TOKEN", Home(cfg_for(self.ha.url), "").problem)

    def test_hostile_room_name_cannot_break_the_template(self):
        h = self.home(rooms=["Kit'chen}} {{ evil"])
        h.set_manual("Kit'chen}} {{ evil")
        self.assertEqual(h.where()[0], "Kit'chen}} {{ evil")
        h.act("status")          # must not raise; the quote characters are removed before the template is built

    # ---- what Claude is told ------------------------------------------------------------------------------------
    def test_status_lines(self):
        h = self.home()
        for value, label in ((10, "dark"), (60, "dim"), (200, "bright")):
            self.assertIn(label, " ".join(h.status_lines(value)))
        self.hour = 23
        text = " ".join(self.home().status_lines(10))
        self.assertIn("Quiet hours", text)
        self.assertNotIn(TOKEN, text)
        self.ha.states["sensor.bob_area"] = "unknown"
        self.clock.t += 60
        self.assertIn("Room: unknown", " ".join(self.home().status_lines(None)))

    def test_clock_parsing(self):
        self.assertEqual(parse_clock("7:05"), (7, 5))
        self.assertIsNone(parse_clock(""))
        with self.assertRaises(ValueError):
            parse_clock("noon")
        self.assertEqual(slug("Living  Room!"), "living_room")

    def test_ping(self):
        self.assertEqual(HomeAssistant(self.ha.url, TOKEN).ping(), "API running.")
        with self.assertRaises(HomeError):
            HomeAssistant(self.ha.url, "nope").ping()


class ThroughTheRobot(unittest.TestCase):
    """The console commands and Claude's tool, with the real controller (simulated hardware)."""

    def setUp(self):
        import bob
        self.ha = FakeHA()
        self.addCleanup(self.ha.stop)
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        os.environ["HA_TOKEN"] = TOKEN
        cfg = config.Config()
        cfg.stream.enabled = False
        cfg.home = cfg_for(self.ha.url, quiet_start="", quiet_end="", cooldown_s=0.0)
        self.ctrl = bob.Controller(cfg, sim=True, paused=True)
        self.addCleanup(self.ctrl.shutdown)

    def test_console_commands(self):
        self.assertIn("Kitchen", self.ctrl.handle("/where"))
        self.assertIn("Living Room", self.ctrl.handle("/where living room"))
        self.assertIn("1 light", self.ctrl.handle("/home status"))
        self.assertIn("Turned", self.ctrl.handle("/home on 50"))
        self.assertEqual(self.ha.calls[-1][1]["brightness_pct"], 50)
        self.assertIn("reachable", self.ctrl.handle("/home check"))

    def test_claude_tool_respects_the_operator_switch(self):
        self.ctrl.controls.auto = True                      # a paused Bob is blocked before the tool is even looked at
        self.ctrl.brain._gen = self.ctrl.controls.stop_gen
        text, err = self.ctrl.brain._dispatch("home", {"action": "on"})
        self.assertFalse(err)
        self.ctrl.handle("/home ai off")
        text, err = self.ctrl.brain._dispatch("home", {"action": "on"})
        self.assertTrue(err)
        self.assertTrue(text.startswith("BLOCKED"))
        self.assertEqual(len(self.ha.calls), 1)

    def test_tool_exists_only_when_home_is_set_up(self):
        names = {t["name"] for t in self.ctrl.brain.tools}
        self.assertIn("home", names)

    def test_claude_never_sees_the_token_or_light_names(self):
        status = self.ctrl.brain._status([], False)
        self.assertNotIn(TOKEN, status)
        self.assertNotIn("kitchen_ceiling", status)
        self.assertIn("Room: Kitchen", status)


if __name__ == "__main__":
    unittest.main()
