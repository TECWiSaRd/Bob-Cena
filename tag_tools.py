#!/usr/bin/env python3
"""Make printable room tags for Bob.

    .venv/bin/python tag_tools.py make 1=Kitchen "2=Living Room" 3=Bedroom
    .venv/bin/python tag_tools.py make 1=Kitchen --cm 8 --family tag36h11 --out tags

Each tag is saved as a PNG sized for US Letter paper at 300 dpi (print at 100% / "actual size", not "fit to page").
Then put the room names in config.toml, for example:  tags = { 1 = "Kitchen", 2 = "Living Room" }
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DPI = 300
PAGE = (int(8.5 * DPI), int(11 * DPI))   # width, height in pixels


def make_tag_image(cv2, np, family: str, ident: int, label: str, cm: float):
    from tags import FAMILIES
    dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, FAMILIES[family]))
    side = int(round(cm / 2.54 * DPI))
    if hasattr(cv2.aruco, "generateImageMarker"):
        marker = cv2.aruco.generateImageMarker(dictionary, ident, side)
    else:
        marker = cv2.aruco.drawMarker(dictionary, ident, side)
    page = np.full((PAGE[1], PAGE[0]), 255, np.uint8)
    x, y = (PAGE[0] - side) // 2, 500
    page[y:y + side, x:x + side] = marker          # the page is white, so the tag has a wide white margin around it
    for i, (text, scale, thick) in enumerate(((f"Room tag {ident}: {label}", 2.6, 6),
                                              (f"{cm:g} cm square. Print at actual size.", 1.4, 3),
                                              ("Stick it flat, low on the wall near the door, inside the room.", 1.2, 2))):
        w = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)[0][0]
        cv2.putText(page, text, (max(20, (PAGE[0] - w) // 2), y + side + 200 + i * 130),
                    cv2.FONT_HERSHEY_SIMPLEX, scale, 0, thick, cv2.LINE_AA)
    return page


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["make"])
    ap.add_argument("tags", nargs="+", help='NUMBER=Room name, for example 1=Kitchen')
    ap.add_argument("--cm", type=float, default=10.0, help="side length of the printed tag in cm (default 10)")
    ap.add_argument("--family", default="tag36h11", choices=["tag36h11", "tag25h9", "aruco4x4_50"])
    ap.add_argument("--out", default="tags", help="folder for the PNG files")
    args = ap.parse_args(argv)
    try:
        import cv2
        import numpy as np
        cv2.aruco
    except (ImportError, AttributeError):
        print("This needs OpenCV with the aruco module: run it on the Pi with  .venv/bin/python tag_tools.py ...")
        return 1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for spec in args.tags:
        num, _, room = spec.partition("=")
        if not num.isdigit() or not room.strip():
            print(f"'{spec}' should look like 1=Kitchen")
            return 1
        path = out / f"tag-{num}-{re.sub(r'[^a-z0-9]+', '-', room.lower()).strip('-')}.png"
        cv2.imwrite(str(path), make_tag_image(cv2, np, args.family, int(num), room.strip(), args.cm))
        print(f"wrote {path}")
    print("Print at 100% (actual size). Then in config.toml under [home]:  tags = { "
          + ", ".join(f'{s.partition("=")[0]} = "{s.partition("=")[2]}"' for s in args.tags) + " }")
    return 0


if __name__ == "__main__":
    sys.exit(main())
