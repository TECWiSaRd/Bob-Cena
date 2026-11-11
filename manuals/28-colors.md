# Manual 28: Seeing colours

Bob can tell you which colours his camera sees and where they are. It runs on the Pi with OpenCV (nothing to download), only looks,
and never moves the wheels.

## Using it

| Command | What it does |
|---|---|
| `/color` | everything he can see: each colour's biggest patch, how much of the picture it fills, and which way it is |
| `/color red` | just red (or `orange`, `yellow`, `green`, `cyan`, `blue`, `purple`, `pink`, `white`, `black`) |
| `/color center` | the hue, saturation and value of the middle of the picture, and what he would call it. Point him at an object to tune the settings |

An answer looks like: `red: biggest patch fills 12% of the picture, 18 degrees to the right, in the middle`. A bearing is measured from straight
ahead using the camera's field of view (`fov_deg` in `[camera]`); **left is the left of the picture**.

Claude can use the same thing through a **see_colors** tool, so "where is the red ball?" is answered by measuring, not by guessing from the photo.
It takes only a colour name, and cannot drive.

## How it works

The picture is shrunk, blurred a little, and turned into **hue / saturation / value**: hue is which colour, saturation is how vivid, value is how
bright. A pixel gets a colour name from its hue if it is vivid and bright enough; very pale and bright is **white**, very dark is **black**.
For each colour the biggest connected patch is kept (so a red ball wins over a few red specks) and tiny patches are ignored.

## Tuning (`[colors]` in `config.local.toml`)

| Setting | Meaning | Default |
|---|---|---|
| `enabled` | colour finding and the `see_colors` tool | `true` |
| `min_percent` | a colour's biggest patch must fill at least this % of the picture | `1.0` |
| `min_saturation` | duller than this (0 to 255) is not called a colour. Lower it for pale colours or dim rooms | `90` |
| `min_value` | darker than this (0 to 255) is not given a colour | `60` |
| `white_saturation`, `white_value` | white is this pale or paler, and at least this bright | `40`, `190` |
| `black_value` | black is darker than this | `45` |

**If a colour isn't found:** use `/color center` on it. If the name says "no colour name", the colour is too dull or too dim: lower `min_saturation`
or `min_value`, or turn on a light. Lighting changes colours a lot (yellow room light makes white look orange), so test where Bob will really be.

## Limits

- It names colours by hue, so a brown or beige thing comes out orange, yellow or red-ish; grey is not reported.
- It reports the *biggest patch of each colour*, not a count of objects. Two red balls are one red patch if they touch.
- It is tested with made-up pictures, not with your camera and lighting yet.
