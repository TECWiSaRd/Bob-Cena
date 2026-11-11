"""What colours is the camera looking at, and where?

Runs on the Pi with OpenCV and nothing else: no network, no model file. The picture is shrunk, turned into hue / saturation / value
(HSV, which separates "which colour" from "how bright"), and each named colour gets a mask. For every colour we keep the biggest
connected patch, so a red ball is found even if there is a little red elsewhere, and report how much of the picture it fills and which
way it is (a bearing from the camera's field of view, negative = left).

It only looks. Nothing here drives the wheels; /color and Claude's see_colors tool just describe the picture.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger("bob.colors")

SIZE = (160, 120)           # the picture is shrunk to this first: fast, and smooths out noise

# Hue ranges in OpenCV's units (0-179, a half-turn of the colour wheel). Red wraps round, so it has two.
HUES = {
    "red": [(0, 9), (170, 179)],
    "orange": [(10, 21)],
    "yellow": [(22, 33)],
    "green": [(34, 84)],
    "cyan": [(85, 99)],
    "blue": [(100, 129)],
    "purple": [(130, 150)],
    "pink": [(151, 169)],
}
GREYS = ("white", "black")
NAMES = tuple(HUES) + GREYS


@dataclass
class ColorBlob:
    name: str
    percent: float      # how much of the picture the biggest patch of this colour fills
    total: float        # how much of the picture is this colour altogether
    cx: float           # the patch's centre as a fraction of the picture (0 = left edge, 1 = right edge)
    cy: float           # 0 = top, 1 = bottom
    w: float
    h: float
    bearing: float      # degrees from straight ahead; negative = left


def direction_words(bearing: float) -> str:
    if abs(bearing) < 6:
        return "straight ahead"
    return f"{abs(bearing):.0f} degrees to the {'right' if bearing > 0 else 'left'}"


def height_words(cy: float) -> str:
    return "high up" if cy < 0.34 else "low down" if cy > 0.66 else "in the middle"


class ColorFinder:
    def __init__(self, cfg, fov_deg: float):
        import cv2
        import numpy as np
        self.cv2, self.np, self.cfg, self.fov = cv2, np, cfg, fov_deg

    def _hsv(self, bgr):
        cv2 = self.cv2
        small = cv2.resize(bgr, SIZE, interpolation=cv2.INTER_AREA)
        return cv2.cvtColor(cv2.GaussianBlur(small, (5, 5), 0), cv2.COLOR_BGR2HSV)

    def _mask(self, hsv, name: str):
        np, cfg = self.np, self.cfg
        h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
        if name == "white":
            return (s <= cfg.white_saturation) & (v >= cfg.white_value)
        if name == "black":
            return v <= cfg.black_value
        colourful = (s >= cfg.min_saturation) & (v >= cfg.min_value)
        hue = np.zeros(h.shape, dtype=bool)
        for lo, hi in HUES[name]:
            hue |= (h >= lo) & (h <= hi)
        return colourful & hue

    def analyze(self, bgr, only: str | None = None) -> list[ColorBlob]:
        """Every colour with a patch big enough to count (or just [only]), biggest first."""
        cv2, np, cfg = self.cv2, self.np, self.cfg
        hsv = self._hsv(bgr)
        total_px = float(hsv.shape[0] * hsv.shape[1])
        kernel = np.ones((3, 3), np.uint8)
        blobs = []
        for name in ([only] if only else NAMES):
            mask = self._mask(hsv, name).astype(np.uint8)
            all_px = float(mask.sum())
            if all_px / total_px * 100 < cfg.min_percent:
                continue
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)          # drop single speckles
            count, _, stats, centres = cv2.connectedComponentsWithStats(mask, connectivity=8)
            if count < 2:
                continue
            best = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
            area = float(stats[best, cv2.CC_STAT_AREA])
            if area / total_px * 100 < cfg.min_percent:
                continue
            cx, cy = float(centres[best][0]) / hsv.shape[1], float(centres[best][1]) / hsv.shape[0]
            blobs.append(ColorBlob(
                name=name, percent=area / total_px * 100, total=all_px / total_px * 100, cx=cx, cy=cy,
                w=float(stats[best, cv2.CC_STAT_WIDTH]) / hsv.shape[1], h=float(stats[best, cv2.CC_STAT_HEIGHT]) / hsv.shape[0],
                bearing=(cx - 0.5) * self.fov))
        return sorted(blobs, key=lambda b: -b.percent)

    def centre(self, bgr) -> tuple[int, int, int, str]:
        """The hue, saturation and value of the middle of the picture, and what we would call it: for tuning the settings."""
        hsv = self._hsv(bgr)
        h, w = hsv.shape[:2]
        patch = hsv[h // 2 - 4:h // 2 + 4, w // 2 - 4:w // 2 + 4].reshape(-1, 3)
        hh, ss, vv = (int(round(float(x))) for x in self.np.median(patch, axis=0))
        one = self.np.array([[[hh, ss, vv]]], dtype=self.np.uint8)
        for name in NAMES:
            if bool(self._mask(one, name)[0, 0]):
                return hh, ss, vv, name
        return hh, ss, vv, "no colour name (too dull or too dim: see min_saturation and min_value)"


def describe(blobs: list[ColorBlob], limit: int = 5) -> str:
    """Plain words for a list of blobs."""
    if not blobs:
        return "no clear colours (nothing fills enough of the picture)"
    lines = []
    for b in blobs[:limit]:
        lines.append(f"{b.name}: biggest patch fills {b.percent:.0f}% of the picture, {direction_words(b.bearing)}, "
                     f"{height_words(b.cy)}" + (f" ({b.total:.0f}% in all)" if b.total - b.percent >= 3 else ""))
    return "; ".join(lines)
