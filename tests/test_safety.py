"""Checks for the safety-critical bits that don't need hardware. Run:  python3 -m unittest discover -s tests"""
import http.client
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from brain import Memory, People  # noqa: E402


def load_toml(text: str):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "c.toml"
        p.write_text(text)
        return config.load(p)


class ConfigValidation(unittest.TestCase):
    def test_project_config_loads(self):
        config.load(Path(__file__).resolve().parent.parent / "config.toml")

    def test_shipped_config_keeps_personal_and_network_features_off(self):
        shipped = Path(__file__).resolve().parent.parent / "config.toml"
        with tempfile.TemporaryDirectory() as d:                    # a copy, so a local override on this machine can't hide a change
            (Path(d) / "config.toml").write_text(shipped.read_text())
            cfg = config.load(Path(d) / "config.toml")
        self.assertFalse(any([cfg.timeline.enabled, cfg.home.enabled, cfg.remote.enabled, cfg.index.ai]))
        self.assertEqual(cfg.home.rooms, [])
        self.assertNotIn("dashboard", cfg.power.who)

    def test_config_local_toml_wins_and_is_checked_like_the_rest(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "config.toml").write_text("[home]\nurl = \"http://a:8123\"\n")
            (Path(d) / "config.local.toml").write_text("[home]\nenabled = true\n")
            cfg = config.load(Path(d) / "config.toml")
            self.assertTrue(cfg.home.enabled)
            self.assertEqual(cfg.home.url, "http://a:8123")
            (Path(d) / "config.local.toml").write_text("[home]\nenabeld = true\n")
            with self.assertRaisesRegex(ValueError, "unknown setting"):
                config.load(Path(d) / "config.toml")

    def test_drive_type_typo_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "isn't one of"):
            load_toml('[drive]\ntype = "dcc"\n')

    def test_unknown_section_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown section"):
            load_toml("[strem]\nenabled = false\n")

    def test_unknown_setting_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown setting"):
            load_toml("[drive]\nmax_sped = 0.5\n")

    def test_mic_aliases_still_work(self):
        self.assertEqual(load_toml('[mic]\nmode = "PTT"\n').mic.mode, "PTT")

    def test_each_choice_default_is_allowed(self):
        cfg = config.Config()
        for (section, key), allowed in config.CHOICES.items():
            self.assertIn(getattr(getattr(cfg, section), key).lower(), allowed, (section, key))


class Notes(unittest.TestCase):
    def test_corrupt_memory_does_not_stop_start(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "memory.json"
            p.write_text('["half a fi')
            m = Memory(p)
            self.assertEqual(m.notes, [])
            self.assertTrue((Path(d) / "memory.json.bad").exists())
            m.add("hello")
            self.assertEqual(json.loads(p.read_text()), ["hello"])
            self.assertFalse((Path(d) / "memory.json.tmp").exists())

    def test_wrong_shape_memory_is_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "memory.json"
            p.write_text('{"a": 1}')
            self.assertEqual(Memory(p).notes, [])

    def test_people_saved_atomically(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "people.json"
            ppl = People(p)
            ppl.remember("Sam", "red cap", "likes robots")
            self.assertIn("Sam", json.loads(p.read_text()))
            self.assertFalse((Path(d) / "people.json.tmp").exists())


class FakeController:
    def __init__(self):
        self.ran = []

    def handle(self, text, by=None, role="owner"):
        self.ran.append(text)
        return "ok"


class Dashboard(unittest.TestCase):
    def _server(self, token):
        import stream
        os.environ["BOB_STREAM_TOKEN"] = token
        cfg = config.StreamConfig()
        cfg.host, cfg.port = "0.0.0.0", 0
        srv = stream.StreamServer(cfg, camera=object())   # these tests never ask for a picture
        srv.controller = FakeController()
        srv.start()
        self.addCleanup(srv._httpd.server_close)
        self.addCleanup(srv._httpd.shutdown)
        return srv

    def _post(self, srv, headers, body=b""):
        port = srv._httpd.server_address[1]
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.putrequest("POST", "/api/cmd?token=correct-horse")
        for k, v in headers.items():
            c.putheader(k, v)
        c.endheaders(body)
        r = c.getresponse()
        return r.status

    def test_negative_content_length_rejected(self):
        srv = self._server("correct-horse")
        self.assertEqual(self._post(srv, {"Content-Type": "application/json", "Content-Length": "-1"}), 400)

    def test_oversize_content_length_rejected(self):
        srv = self._server("correct-horse")
        self.assertEqual(self._post(srv, {"Content-Type": "application/json", "Content-Length": "999999"}), 413)

    def test_missing_content_length_rejected(self):
        srv = self._server("correct-horse")
        self.assertEqual(self._post(srv, {"Content-Type": "application/json"}), 411)

    def test_no_token_binds_to_loopback_only(self):
        srv = self._server("")
        self.assertEqual(srv._httpd.server_address[0], "127.0.0.1")

    def test_token_allows_configured_host(self):
        srv = self._server("correct-horse")
        self.assertEqual(srv._httpd.server_address[0], "0.0.0.0")


if __name__ == "__main__":
    unittest.main()
