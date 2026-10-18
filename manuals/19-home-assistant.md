# Manual 19: Home Assistant (lights)

Bob can turn the lights on and off in the room he's in, through Home Assistant (HA). This manual explains
what he can and can't do, how to set it up, how he knows which room he's in, and how to fix problems.

**Status:** tested against a simulated Home Assistant, and room tags against computer-made pictures of tags.
Neither has been tried yet on the real thing, so expect to adjust: the camera's view of the tags, where you
put them, and the Bluetooth room tracking in particular.

---

## What Bob can do, and what he can't

**He can:** check how many lights are on in his room, and turn them all on (optionally at a brightness) or
all off.

**He can't:**
- touch anything that isn't a light (locks, switches, covers, climate, alarms and so on)
- touch a room that isn't in your `rooms` list
- touch a room he isn't in
- use the lights if he doesn't know which room he's in
- see what your lights are called (he's told only "2 lights in the Kitchen: 1 on, 1 off")

These limits are in Bob's code, not in Claude's instructions, so Claude can't talk his way around them.

## Safety limits on top

| Limit | Default | Why |
|---|---|---|
| **Quiet hours:** no turning lights **on** | 22:00 to 07:00 | so he doesn't light up a bedroom at 2 a.m. Turning off is always allowed |
| **Cooldown** per room | 30 seconds | so he can't flicker the lights |
| **Rate limit** | 6 changes a minute | a safety net |
| **Operator switch** | on | `/home ai off` takes the lights away from Claude at any time |
| **Your own commands** | not limited | `/home on` and `/home off` ignore quiet hours and cooldowns, because you're the operator |

Every change he makes is recorded in the [timeline](14-memory-and-people.md) (when it's on) as a `home` event.

---

## Setting it up

### 1. Make a token in Home Assistant

1. In Home Assistant, open your profile (your name, bottom left).
2. Go to the **Security** tab, scroll to **Long-lived access tokens**, and create one called "Bob".
3. Copy it now. It's shown only once.

Better: create a **separate Home Assistant user** for Bob (Settings → People → Users) and make the token
there, so you can see Bob's actions in the logbook and remove his access without affecting yours. I'm not sure
how strictly Home Assistant limits a non-administrator user through its API, so treat Bob's own limits above
as the real protection.

### 2. Put it on the Pi

```bash
nano ~/bob/.env
```
Add a line (no quotes):
```
HA_TOKEN=paste-the-token-here
```
Keep `.env` private, like your API key.

### 3. Tell Bob which rooms

In `config.toml` (edit on your Mac, then copy it over):

```toml
[home]
enabled = true
url = "http://192.168.1.20:8123"        # your Home Assistant's address (the Pi 5)
rooms = ["Kitchen", "Living Room"]      # Home Assistant AREAS Bob may control
location_entity = "sensor.bob_area"     # see below; leave empty for now to use /where
```

`rooms` are the **areas** you've set up in Home Assistant (Settings → Areas). Bob controls the `light.*`
entities assigned to each area, either directly or through their device. Use the area's name exactly as
Home Assistant shows it. Use an IP address for `url` if `homeassistant.local` doesn't resolve from the Pi.

### 4. Restart Bob and test

```
/home check          is Home Assistant reachable, and does he know his room?
/where kitchen       tell him where he is
/home status         "2 lights in the Kitchen: 1 on, 1 off."
/home on 40          turn them on at 40% (your command, so no limits)
/home off
```
`/check` also has a `home assistant` line.

---

## How Bob knows which room he's in

Bob can't work out his position by counting wheel turns, so he needs to be told or to read it from somewhere.
He tries these in order:

1. **You tell him:** `/where kitchen` (and `/where clear` to go back to automatic). This always wins. It stays
   until you clear it, so remember to update it when you carry him somewhere else.
2. **A room tag** he has seen recently: a printed AprilTag by each door. See "Room tags" below. No extra
   hardware, works today.
3. **A room sensor in Home Assistant** (`location_entity`). If Home Assistant already tracks Bluetooth devices
   by room, it can produce a sensor whose state is the room name, such as `sensor.bob_area`. Bob reads it
   every few seconds. If it says `unknown`, `unavailable` or `not_home`, or names a room that isn't in your
   `rooms` list, he treats his room as unknown and won't touch any lights.
4. **Not known:** he says so and leaves the lights alone.

You can use tags only, Bluetooth only, or both. With both, a recent tag sighting wins and Bluetooth fills in
the rest of the time. Use `/where` to see which one he's going by.

### Room tags (AprilTags)

A tag is a printed black-and-white square, like a QR code, with a number in it. Stick one near the door of
each room. When Bob's camera sees it close up, he knows the room.

**1. Print them.** On the Pi (it needs the OpenCV that's already installed there):

```bash
cd ~/bob
.venv/bin/python tag_tools.py make 1=Kitchen "2=Living Room" 3=Bedroom
```
This writes `tags/tag-1-kitchen.png` and so on, one letter-size page each, and prints the line to paste into
your config. Copy the PNGs to your computer (for example with `scp`) and print them at **100% / actual size**,
not "fit to page". The default tag is 10 cm square; use `--cm 15` for a bigger one that works from further away.

**2. Tell Bob what the numbers mean.** In `config.toml`:

```toml
[home]
tags = { 1 = "Kitchen", 2 = "Living Room", 3 = "Bedroom" }
```
The room names must also appear in `rooms` (otherwise he'll see the tag but won't be allowed to control that
room's lights).

**3. Stick them up, at Bob's eye level.** Bob's camera is only a few centimetres off the floor. Put each tag
flat on the wall or furniture **10 to 30 cm above the floor**, inside the room, near the door he'd come in by.
Matt paper or a matt laminate is better than glossy, which reflects the lights.

**4. Test it.** Point Bob at a tag from about a metre away and type `/tags`:

```
  tag 2: 71 px wide (counts: the Living Room)
  Bob's room now: Living Room (seen on room tag 2)
```
If it says "ignored: too small", he's too far away. Move him closer, or print a bigger tag.

**How far away does a tag work?** A tag is only believed if it looks at least `tag_min_px` (40) pixels wide.
With a 10 cm tag and a typical 62-degree camera that's about 1.3 metres, and about 2 metres for a 15 cm tag.
The limit is deliberate: it stops Bob from reading a tag in the next room through an open door.

**What he does when he can't see one.** He can't feel himself leaving a room, so the knowledge fades:
- after `tag_valid_s` (5 minutes), or
- once his wheels have run `tag_max_move_s` (20 seconds) since he last saw a tag, whichever comes first.

Then he doesn't know his room, says so, and leaves the lights alone. A tag must be seen in two pictures in a
row to be believed, which filters out false detections.

**Making him look around.** Type `/locate` and Bob turns slowly on the spot, a short step at a time, stopping
to look after each one (the picture blurs while he turns), until he sees and confirms a room tag. Then he stops
and says "I'm in the Kitchen." He never drives forward while doing this.

- `/locate 40` looks for up to 40 seconds (the default is `tag_search_seconds`, 25). `/locate off` stops it.
- If he already knows his room, he says so and doesn't move.
- If he turns for the whole time without seeing a tag, he gives up and says so. Move him to somewhere he can
  see a tag from, or tell him with `/where`.
- Claude can do the same himself with the `find_my_room` tool when his status says his room is unknown and he
  wants the lights. It obeys `/motion off`, `/pause`, and the emergency stop like every other movement.
- Because it turns the whole robot, clear the area first. A full turn is a wide sweep for his cables and
  anything near him.

### Getting Bluetooth room tracking (the part I haven't tested)

Home Assistant needs something that can hear a Bluetooth signal from Bob in each room:
- **Bluetooth proxies**, such as ESPHome Bluetooth proxy devices (cheap ESP32 boards), one per room.
- Something that turns the signal strengths into a room, such as the community **Bermuda** integration, which
  gives each tracked device an area sensor.

Bob also has to *be* a Bluetooth device that those can see. The simplest, most dependable way is a **small
Bluetooth tag** (a beacon) stuck on his body. Having the Pi itself advertise could clash with the music
pairing, so I haven't set that up. The sensor Bermuda creates for the tag is what you put in `location_entity`.

Links are in [Resources](18-resources.md). If room tracking works poorly (jumping between rooms, slow to
change), room tags and `/where` still work, and the two can be used together.

---

## How he decides it's dark

Each tick, Bob measures the brightness of his own camera picture and tells Claude a label:

| Label | Camera brightness (0 to 255) |
|---|---|
| dark | below `dark_below` (40) |
| dim | between the two |
| bright | above `bright_above` (90) |

Camera auto-exposure brightens dark scenes, so this is a rough guide, not a light meter. Claude also looks
at the picture itself. You can adjust the two numbers in `[home]` after watching what your camera reports.

---

## Settings

All in `[home]`. See also [Settings reference](15-settings-reference.md).

| Setting | Default | What it does |
|---|---|---|
| `enabled` | false | switch it on |
| `url` | `http://homeassistant.local:8123` | your Home Assistant |
| `rooms` | `[]` | the areas Bob may control |
| `location_entity` | `""` | sensor whose state is Bob's room |
| `tags` | `{}` | room tags: tag number to room name, such as `{ 1 = "Kitchen" }` |
| `tag_family` | `"tag36h11"` | the kind of tag (`tag36h11` is the standard AprilTag; also `tag25h9`, `aruco4x4_50`) |
| `tag_min_px` | 40 | a tag must look at least this wide, in pixels, to be believed (so he's close to it) |
| `tag_valid_s` | 300 | how long a sighting is trusted |
| `tag_max_move_s` | 20 | ...and until the wheels have run this many seconds since it |
| `tag_scan_hz` | 3 | how often the camera is checked for tags |
| `tag_search_speed` | 0.35 | how fast he turns when looking for a tag (`/locate`, `find_my_room`) |
| `tag_search_seconds` | 25 | how long he looks before giving up |
| `quiet_start`, `quiet_end` | `"22:00"`, `"07:00"` | no turning lights on between these. Empty = never quiet |
| `max_per_minute` | 6 | light changes Claude may make a minute |
| `cooldown_s` | 30 | least time between changes to the same room |
| `dark_below`, `bright_above` | 40, 90 | camera brightness cut-offs |

## Commands

| Command | What it does |
|---|---|
| `/home` | how many lights are on in his room |
| `/home on [percent]` / `/home off` | switch his room's lights (your command: no limits) |
| `/home check` | is Home Assistant reachable, and does he know his room? |
| `/home ai on` / `off` | let Claude use the lights, or take them away |
| `/locate [seconds]` | Bob turns slowly on the spot until he sees a room tag. `/locate off` stops |
| `/tags` | which room tags the camera sees right now, how big they look, and what room he's in |
| `/where` | which room he thinks he's in, and why |
| `/where kitchen` / `/where clear` | tell him, or go back to automatic |

---

## Privacy and security

- The token lives only in `.env` on the Pi. It is never shown to Claude, never logged and never put in the
  timeline.
- Claude sees the room name, the light level and counts of lights. He doesn't see device names or any other
  part of your home.
- Bob talks to Home Assistant over your home network, in plain `http` unless you've set up `https`. That's
  normal at home. Don't point Bob at a Home Assistant exposed to the internet without `https`.

## Troubleshooting

| Problem | Fix |
|---|---|
| `Home Assistant disabled: set HA_TOKEN in .env` | add the token and restart Bob |
| `Home Assistant disabled: [home] rooms is empty` | list at least one area in `rooms` |
| `can't reach Home Assistant` | check `url` (try the IP address) and that the Pi can reach the Pi 5: `curl http://<address>:8123` |
| `rejected the access token` | the token is wrong or was deleted: make a new one |
| `I don't know which room I'm in` | `/where <room>`, show him a tag, or fix the room sensor |
| `/locate` ends with "saw no room tag" | the tags aren't in view from where he stands, or are too small or at the wrong height. Try `/tags` while he faces one |
| `/tags` says `no tags in view` | the tag may be too high or too low for his camera: check with `/snap`. Also glare, a crumpled tag, or too dark |
| `/tags` says `ignored: too small` | he's too far away: get closer, or print a bigger tag (`--cm 15`) |
| `room tags unavailable: this OpenCV has no aruco module` | the Pi's OpenCV lacks the tag reader. Try `.venv/bin/pip install opencv-contrib-python-headless`, then restart Bob. I haven't tried this on a Pi, so if it fails, tell me the error |
| He swaps rooms after passing a doorway | the tag was seen from the wrong side: move it inside the room, further from the door, or raise `tag_min_px` |
| `no lights in the Kitchen that I can control` | the area has no `light.*` entities: check Settings → Areas, and that the lights (or their devices) are assigned to that area |
| `Quiet hours` | by design. Change `quiet_start` and `quiet_end`, or set both to `""` |
| `wait 25s` | the cooldown, by design |
| The room sensor keeps jumping | Bluetooth signals bounce around. Use `/where`, or add another proxy in the room |
