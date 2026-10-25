#!/usr/bin/env python3
"""Make the Mac app's icon from a 1024 x 1024 logo.

    pip install pillow
    python3 app/tool/make_mac_icon.py                       # uses the Liquid Glass export if there is one, else temp/bob-app_logo.png
    python3 app/tool/make_mac_icon.py path/to/logo.png

A plain square picture is put in Apple's standard icon shape (a rounded square with a margin and a soft shadow, as macOS expects).
A picture that already has its own rounded shape (transparent corners, like an Icon Composer export) is only shrunk onto the
icon grid and given the shadow. Every size the app needs is written into macos/Runner/Assets.xcassets/AppIcon.appiconset. Rebuild the app afterwards
(cd app && flutter build macos). temp/bob-app_icon_macos_preview.png shows the result.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent.parent
GLASS = ROOT / "temp" / "Bobapplogo-liquidglass Exports" / "Bobapplogo-liquidglass-iOS-Default-1024@1x.png"
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else (GLASS if GLASS.exists() else ROOT / "temp" / "bob-app_logo.png")
OUT = ROOT / "app" / "macos" / "Runner" / "Assets.xcassets" / "AppIcon.appiconset"

img = Image.open(SRC).convert("RGBA")
if img.size != (1024, 1024):
    sys.exit(f"{SRC} is {img.size[0]} x {img.size[1]}; it should be 1024 x 1024 pixels")

BODY, CANVAS, RADIUS = 824, 1024, 185          # Apple's macOS icon grid
art = img.resize((BODY, BODY), Image.LANCZOS)
if img.getchannel("A").getextrema()[0] < 250:                      # it already has its own shape: keep it
    mask = art.getchannel("A")
else:
    mask = Image.new("L", (BODY * 4, BODY * 4), 0)                 # drawn 4x larger, then shrunk, for smooth edges
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, BODY * 4 - 1, BODY * 4 - 1), radius=RADIUS * 4, fill=255)
    mask = mask.resize((BODY, BODY), Image.LANCZOS)

icon = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
shadow = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
shadow.paste((0, 0, 0, 90), ((CANVAS - BODY) // 2, (CANVAS - BODY) // 2 + 10), mask)
icon = Image.alpha_composite(icon, shadow.filter(ImageFilter.GaussianBlur(14)))
icon.paste(art, ((CANVAS - BODY) // 2, (CANVAS - BODY) // 2), mask)

for size in (16, 32, 64, 128, 256, 512, 1024):
    icon.resize((size, size), Image.LANCZOS).save(OUT / f"app_icon_{size}.png")
preview = ROOT / "temp" / "bob-app_icon_macos_preview.png"
preview.parent.mkdir(exist_ok=True)
icon.save(preview)
print(f"Wrote the icon sizes to {OUT.relative_to(ROOT)}; preview: {preview.relative_to(ROOT)}")
