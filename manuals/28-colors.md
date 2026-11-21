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

## Following a colour

`/color follow red` (or any of the colour names) makes Bob **turn toward that colour and drive up to it, and keep doing that until you stop him**.
There is no time limit.

| Command | What it does |
|---|---|
| `/color follow COLOR` | start following. The AI is paused while he does (it stays paused until `/resume`) |
| `/color follow off` | stop |

**What ends it:** `/color follow off`, `/stop`, saying "stop", the emergency stop (`/estop`, Space), `/pause`, `/motion off`, `/resume` (the AI is allowed to think
again), starting `/drive` or moving the joystick (someone else is driving), a lost camera picture (after 2 seconds), or an error. Every wheel command lasts
only a fraction of a second, so if Bob's program ever died he would stop by itself. The speed cap, the emergency stop and the distance sensor
(which refuses forward moves toward something close) apply as for any other driving. Claude has no tool to start it.

**How close he gets** is set by `follow_percent` (the colour fills that much of the picture; a bigger number means closer) and, if you have a distance sensor, by
`follow_distance_cm` (for example `40` to stop about 40 cm away). He stops coming closer when **either** says he is near enough. These can be changed live with
`/set colors.follow_percent 25` and `/set colors.follow_distance_cm 40`. To make him **search faster**, `/set colors.follow_search_speed 0.5`. The distance sensor reads straight ahead only, so it measures what is in front of him,
which may not be the colour's object. The sensor's own stop distance (`[sensor] stop_cm`, `/range stop N`) is separate and still refuses to drive forward when something is closer.

**What he does:** a patch on the right turns him right, on the left turns him left; when it is roughly ahead he drives toward it and stops coming closer once it
fills `follow_percent` of the picture. **If the colour is out of sight he turns on the spot until he finds it**: toward where it went if he had seen it (to the right if he
hasn't seen it yet). He turns in short bursts with pauses between them, so the camera gets a sharp picture each time, and as soon as he sees the colour he follows it.
By default he keeps looking for as long as it takes; `follow_search_s` can make him give up turning after that many seconds and wait still (still watching).
He only drives forward: he never reverses toward you. While he looks he only turns, so he doesn't wander across the room.

The colour is judged by hue, so a plain, bright, single-colour object works best (a ball, a sheet of coloured paper). Other things of the same colour in view
(a red sofa behind a red ball) can pull him toward the biggest patch. Test it with `/color red` first to see what he sees.

**Real-Pi checklist** (untested on hardware so far; wheels lifted for the first run, `/speed 0.3`):
1. `/color red` with the object in view: he should report it with a sensible bearing.
2. `/color follow red`: move the object left and right; the wheels should turn toward it (flip `left_invert` or `right_invert` if they turn away).
3. Move it away and back: he should come closer, then stop once it fills enough of the picture.
4. Hide it: he should turn toward where it went, in short bursts with pauses, until he sees it again; then he follows it.
5. `/color follow off`, `/estop` and the joystick must each stop him at once.

## Tuning (`[colors]` in `config.local.toml`)

| Setting | Meaning | Default |
|---|---|---|
| `enabled` | colour finding and the `see_colors` tool | `true` |
| `min_percent` | a colour's biggest patch must fill at least this % of the picture | `1.0` |
| `min_saturation` | duller than this (0 to 255) is not called a colour. Lower it for pale colours or dim rooms | `90` |
| `min_value` | darker than this (0 to 255) is not given a colour | `60` |
| `white_saturation`, `white_value` | white is this pale or paler, and at least this bright | `40`, `190` |
| `black_value` | black is darker than this | `45` |
| `follow_speed` | top speed while following (the `/speed` cap still applies) | `0.4` |
| `follow_distance_cm` | with a distance sensor: he stops coming closer at this distance in cm. `0` = go by picture size only. Keep it above `[sensor] stop_cm` | `0` |
| `follow_percent` | he stops coming closer once the colour fills this much of the picture (used when there is no sensor, or `follow_distance_cm` is 0, and always as well) | `15` |
| `follow_search_speed` | how fast he turns on the spot while looking for a colour that is out of sight, 0 to 1. `0` = automatic (half of `follow_speed`). Faster finds it sooner, but can overshoot it | `0` |
| `follow_deadzone` | ignore a colour this close to the centre line (0 = centre, 1 = edge) | `0.10` |
| `follow_turn_gain` | how hard he turns toward it | `0.9` |
| `follow_search_s` | how long he turns looking for a colour that is out of sight before giving up and waiting still. `0` = keep looking until he finds it | `0` |

**If a colour isn't found:** use `/color center` on it. If the name says "no colour name", the colour is too dull or too dim: lower `min_saturation`
or `min_value`, or turn on a light. Lighting changes colours a lot (yellow room light makes white look orange), so test where Bob will really be.

## Limits

- It names colours by hue, so a brown or beige thing comes out orange, yellow or red-ish; grey is not reported.
- It reports the *biggest patch of each colour*, not a count of objects. Two red balls are one red patch if they touch.
- It is tested with made-up pictures, not with your camera and lighting yet.
