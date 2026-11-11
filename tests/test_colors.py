import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

try:
    import cv2
    import numpy as np
except ImportError:                                  # a Mac venv without OpenCV: these tests are skipped
    cv2 = np = None

import colors  # noqa: E402


def picture(background=(128, 128, 128), size=(480, 640)):
    img = np.zeros((*size, 3), np.uint8)
    img[:] = background
    return img


def paint(img, rgb, x0, y0, x1, y1):
    img[y0:y1, x0:x1] = rgb[::-1]                    # OpenCV pictures are blue-green-red
    return img


@unittest.skipIf(cv2 is None, "needs OpenCV and numpy")
class FindingColours(unittest.TestCase):
    def finder(self, **kw):
        return colors.ColorFinder(config.ColorsConfig(**kw), 62.0)

    def test_each_colour_is_named(self):
        for name, rgb in {"red": (220, 20, 20), "orange": (255, 140, 0), "yellow": (240, 220, 20), "green": (20, 180, 40),
                          "cyan": (20, 200, 220), "blue": (30, 60, 230), "purple": (140, 40, 200), "pink": (255, 80, 170),
                          "white": (250, 250, 250), "black": (5, 5, 5)}.items():
            img = paint(picture((128, 128, 128)), rgb, 200, 160, 440, 320)
            found = [b.name for b in self.finder().analyze(img)]
            self.assertIn(name, found, f"{name} was not found; saw {found}")

    def test_red_wraps_round_the_hue_circle(self):
        for rgb in [(230, 10, 10), (230, 10, 40)]:       # one each side of hue 0
            blobs = self.finder().analyze(paint(picture(), rgb, 100, 100, 300, 300), "red")
            self.assertEqual([b.name for b in blobs], ["red"], rgb)

    def test_where_it_is_and_how_big(self):
        img = paint(picture(), (220, 20, 20), 480, 120, 640, 360)       # the right quarter, vertically in the middle
        blob = self.finder().analyze(img, "red")[0]
        self.assertAlmostEqual(blob.cx, 0.875, delta=0.03)
        self.assertAlmostEqual(blob.cy, 0.5, delta=0.03)
        self.assertAlmostEqual(blob.percent, 12.5, delta=1.0)
        self.assertGreater(blob.bearing, 20)                            # to the right
        left = self.finder().analyze(paint(picture(), (220, 20, 20), 0, 120, 160, 360), "red")[0]
        self.assertLess(left.bearing, -20)

    def test_the_biggest_patch_is_the_one_reported(self):
        img = paint(paint(picture(), (20, 180, 40), 20, 20, 60, 60), (20, 180, 40), 300, 200, 560, 440)
        blob = self.finder().analyze(img, "green")[0]
        self.assertGreater(blob.cx, 0.5)
        self.assertGreater(blob.total, blob.percent)

    def test_specks_and_grey_scenes_find_nothing(self):
        img = picture()
        img[100, 100] = (20, 20, 220)                                   # one red pixel
        self.assertEqual(self.finder().analyze(img, "red"), [])
        self.assertEqual([b.name for b in self.finder().analyze(picture((120, 120, 120)))], [])

    def test_settings_move_the_line(self):
        dull = paint(picture(), (170, 130, 130), 100, 100, 400, 400)    # a pale red
        self.assertEqual(self.finder().analyze(dull, "red"), [])
        self.assertEqual([b.name for b in self.finder(min_saturation=40).analyze(dull, "red")], ["red"])

    def test_the_centre_reading_names_the_middle(self):
        img = paint(picture(), (30, 60, 230), 200, 160, 440, 320)
        h, s, v, name = self.finder().centre(img)
        self.assertEqual(name, "blue")
        self.assertTrue(100 <= h <= 129 and s > 150 and v > 200)
        self.assertIn("no colour name", self.finder().centre(picture((90, 100, 95)))[3])

    def test_the_words(self):
        img = paint(picture(), (220, 20, 20), 480, 120, 640, 360)
        text = colors.describe(self.finder().analyze(img, "red"))
        self.assertIn("red", text)
        self.assertIn("to the right", text)
        self.assertIn("no clear colours", colors.describe([]))
        self.assertEqual(colors.direction_words(2), "straight ahead")


@unittest.skipIf(cv2 is None, "needs OpenCV and numpy")
class ThroughTheRobot(unittest.TestCase):
    def setUp(self):
        import bob
        self.bob = bob
        self.frame = paint(picture(), (30, 60, 230), 0, 0, 200, 480)
        cam = SimpleNamespace(enabled=True, grab_bgr=lambda: self.frame)
        cfg = config.load(Path(__file__).resolve().parent.parent / "config.toml")
        finder = colors.ColorFinder(cfg.colors, 62.0)
        import brain
        self.brain = brain.Brain.__new__(brain.Brain)
        self.brain.colors, self.brain.camera = finder, cam
        self.ctrl = bob.Controller.__new__(bob.Controller)
        self.ctrl.colors, self.ctrl.camera, self.ctrl.brain = finder, cam, self.brain

    def test_the_command(self):
        out = self.ctrl.color_command("")
        self.assertIn("blue", out)
        self.assertIn("left", out)
        self.assertIn("blue", self.ctrl.color_command("blue"))
        self.assertIn("no red", self.ctrl.color_command("red"))
        self.assertIn("usage", self.ctrl.color_command("plaid"))
        self.assertIn("hue", self.ctrl.color_command("center"))

    def test_off_and_camera_off(self):
        self.ctrl.camera.enabled = False
        self.assertIn("camera is off", self.ctrl.color_command(""))
        self.ctrl.camera.enabled = True
        self.ctrl.colors = None
        self.assertIn("off or unavailable", self.ctrl.color_command(""))

    def test_claude_gets_a_read_only_tool_only_when_it_is_on(self):
        import brain
        names = lambda **k: [t["name"] for t in brain.build_tools(3.0, **k)]
        self.assertNotIn("see_colors", names())
        self.assertIn("see_colors", names(colors=True))
        tool = [t for t in brain.build_tools(3.0, colors=True) if t["name"] == "see_colors"][0]
        self.assertEqual(list(tool["input_schema"]["properties"]), ["color"])     # it takes a colour and nothing that could move him


if __name__ == "__main__":
    unittest.main()
