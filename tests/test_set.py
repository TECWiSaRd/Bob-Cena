import os
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402


class SavingToTheFile(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "config.local.toml"

    def read(self):
        return tomllib.loads(self.path.read_text())

    def test_it_creates_the_file_and_the_section(self):
        config.save_local(self.path, "colors", "min_saturation", 70)
        self.assertEqual(self.read(), {"colors": {"min_saturation": 70}})

    def test_it_changes_one_line_and_keeps_everything_else_including_comments(self):
        self.path.write_text('# my settings\n[drive]\nleft_invert = false   # servo\nright_invert = true\n\n[colors]\nmin_value = 60\n')
        config.save_local(self.path, "drive", "left_invert", True)
        text = self.path.read_text()
        self.assertIn("# my settings", text)
        self.assertIn("right_invert = true", text)
        self.assertEqual(self.read(), {"drive": {"left_invert": True, "right_invert": True}, "colors": {"min_value": 60}})

    def test_a_new_key_goes_inside_its_own_section_not_the_next_one(self):
        self.path.write_text("[drive]\nleft_invert = false\n\n[colors]\nmin_value = 60\n")
        config.save_local(self.path, "drive", "right_invert", True)
        self.assertEqual(self.read(), {"drive": {"left_invert": False, "right_invert": True}, "colors": {"min_value": 60}})

    def test_a_new_section_is_added_at_the_end(self):
        self.path.write_text("[drive]\nleft_invert = false\n")
        config.save_local(self.path, "brain", "effort", "high")
        self.assertEqual(self.read(), {"drive": {"left_invert": False}, "brain": {"effort": "high"}})

    def test_a_key_with_the_same_start_is_not_mistaken_for_it(self):
        self.path.write_text("[colors]\nmin_value_x = 1\n")
        config.save_local(self.path, "colors", "min_value", 50)
        self.assertEqual(self.read(), {"colors": {"min_value_x": 1, "min_value": 50}})

    def test_what_is_written_loads_back_as_real_config(self):
        (Path(self.dir.name) / "config.toml").write_text("")
        config.save_local(self.path, "colors", "min_percent", 2.5)
        config.save_local(self.path, "brain", "think_when", "change")
        config.save_local(self.path, "brain", "fallbacks", False)
        cfg = config.load(Path(self.dir.name) / "config.toml")
        self.assertEqual((cfg.colors.min_percent, cfg.brain.think_when, cfg.brain.fallbacks), (2.5, "change", False))

    def test_a_broken_file_is_not_made_worse(self):
        self.path.write_text("[drive\nbroken")
        with self.assertRaises(Exception):
            config.save_local(self.path, "colors", "min_value", 50)
        self.assertEqual(self.path.read_text(), "[drive\nbroken")


class ReadingTheValue(unittest.TestCase):
    def test_types_and_ranges(self):
        p = config.parse_setting
        self.assertEqual(p("colors", "min_saturation", "70"), 70)
        self.assertEqual(p("brain", "tick_seconds", "5"), 5.0)
        self.assertIs(p("brain", "fallbacks", "off"), False)
        self.assertIs(p("drive", "left_invert", "yes"), True)
        self.assertEqual(p("brain", "effort", "high"), "high")
        for section, key, bad in (("colors", "min_saturation", "300"), ("colors", "min_saturation", "x"), ("colors", "min_saturation", "1.5"),
                                  ("brain", "tick_seconds", "0"), ("brain", "tick_seconds", "nan"), ("brain", "tick_seconds", "inf"),
                                  ("brain", "effort", "extreme"), ("brain", "think_when", "sometimes"), ("drive", "left_invert", "maybe")):
            with self.assertRaises(ValueError, msg=f"{key}={bad}"):
                p(section, key, bad)

    def test_safety_limits_and_wiring_cannot_be_set_this_way(self):
        for section, key in (("drive", "max_speed"), ("drive", "max_move_seconds"), ("drive", "dc_left_pwm"), ("drive", "dc_standby"),
                             ("drive", "estop_button_pin"), ("drive", "drive_style"), ("drive", "dc_wheels"), ("remote", "enabled"),
                             ("update", "channel"), ("alerts", "enabled")):
            self.assertNotIn((section, key), config.LIVE_SETTINGS)
            with self.assertRaises(ValueError):
                config.parse_setting(section, key, "1")

    def test_every_live_setting_really_exists_with_a_matching_type(self):
        cfg = config.Config()
        for (section, key), bounds in config.LIVE_SETTINGS.items():
            value = getattr(getattr(cfg, section), key)
            if bounds:
                self.assertTrue(bounds[0] <= value <= bounds[1], f"{section}.{key} default {value} is outside its own range")


class TheCommand(unittest.TestCase):
    def setUp(self):
        import bob
        os.environ["ANTHROPIC_API_KEY"] = "dummy"
        cfg = config.Config()
        cfg.stream.enabled = False
        self.ctrl = bob.Controller(cfg, sim=True, paused=True)
        self.addCleanup(self.ctrl.shutdown)
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.ctrl.local_config = Path(self.dir.name) / "config.local.toml"

    def test_it_changes_the_running_setting_and_saves_it(self):
        out = self.ctrl.handle("/set colors.min_saturation 70")
        self.assertIn("90 -> 70", out)
        self.assertEqual(self.ctrl.cfg.colors.min_saturation, 70)
        self.assertEqual(tomllib.loads(self.ctrl.local_config.read_text()), {"colors": {"min_saturation": 70}})

    def test_the_color_finder_uses_it_at_once(self):
        self.assertIs(self.ctrl.colors.cfg, self.ctrl.cfg.colors) if self.ctrl.colors else None
        self.assertIs(self.ctrl.brain.cfg, self.ctrl.cfg.brain)
        self.ctrl.handle("/set brain.tick_seconds 9")
        self.assertEqual(self.ctrl.brain.cfg.tick_seconds, 9.0)

    def test_once_changes_it_without_saving(self):
        out = self.ctrl.handle("/set brain.effort high once")
        self.assertIn("until Bob restarts", out)
        self.assertEqual(self.ctrl.cfg.brain.effort, "high")
        self.assertFalse(self.ctrl.local_config.exists())

    def test_a_bad_value_changes_nothing(self):
        for line in ("/set colors.min_saturation 999", "/set colors.min_saturation lots", "/set brain.effort extreme"):
            before = self.ctrl.cfg.colors.min_saturation, self.ctrl.cfg.brain.effort
            self.ctrl.handle(line)
            self.assertEqual((self.ctrl.cfg.colors.min_saturation, self.ctrl.cfg.brain.effort), before)
        self.assertFalse(self.ctrl.local_config.exists())

    def test_safety_limits_are_refused_with_a_reason(self):
        out = self.ctrl.handle("/set drive.max_speed 1.0")
        self.assertIn("config.local.toml", out)
        self.assertEqual(self.ctrl.cfg.drive.max_speed, config.DriveConfig().max_speed)
        self.assertFalse(self.ctrl.local_config.exists())

    def test_only_the_owner_can_use_it(self):
        for role in ("operator", "viewer", "dashboard"):
            self.assertIn("only the owner", self.ctrl.handle("/set colors.min_value 10", by="kai", role=role))
        self.assertEqual(self.ctrl.cfg.colors.min_value, config.ColorsConfig().min_value)

    def test_it_lists_and_shows(self):
        self.assertIn("colors.min_saturation = 90", self.ctrl.handle("/set"))
        self.assertEqual(self.ctrl.handle("/set colors.min_value"), "colors.min_value = 60")
        self.assertIn("can't be changed", self.ctrl.handle("/set drive.max_speed"))

    def test_a_file_that_cannot_be_written_still_applies_and_says_so(self):
        self.ctrl.local_config = Path(self.dir.name) / "nope" / "config.local.toml"
        out = self.ctrl.handle("/set colors.min_value 10")
        self.assertIn("couldn't save", out)
        self.assertEqual(self.ctrl.cfg.colors.min_value, 10)

    def test_claude_has_no_way_to_change_settings(self):
        import brain
        names = {t["name"] for t in brain.build_tools(3.0, mecanum=True)}
        self.assertFalse(names & {"set", "set_setting", "config", "settings", "set_config"})


if __name__ == "__main__":
    unittest.main()
