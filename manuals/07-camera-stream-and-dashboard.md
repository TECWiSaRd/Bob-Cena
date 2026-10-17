# Manual 07: Camera, video stream and phone dashboard

The camera is Bob's main sense: Claude sees a picture every tick. This manual covers setting up the camera,
watching what Bob sees from your Mac or phone, and the phone dashboard you can use to control him.

> **Status:** the camera code supports both camera types, but your **USB camera hasn't been confirmed
> working on the Pi yet**. The video stream and the dashboard were tested on a Mac (the dashboard's script
> was checked for errors), but **the dashboard page hasn't been opened in a real phone browser yet**.

---

## Part 1: The camera

### Which camera

| Camera | Connects to | Setting under `[camera]` |
|---|---|---|
| USB webcam | any USB port | `source = "usb"` |
| Raspberry Pi camera module | the ribbon connector | `source = "csi"` |
| Not sure / either | | `source = "auto"` (tries the module first, then USB) |

When Bob starts, the log says which one he found, for example `Camera ready: USB camera (640x480)`. If he
finds none, he logs why and carries on blind (Claude is told he can't see, and to stay put).

### Checking the camera works

**USB camera:**
```bash
lsusb                       # is it listed at all? If not: cable, port or power
v4l2-ctl --list-devices     # which /dev/videoN it uses
```
Webcams often show two entries, such as `/dev/video0` and `/dev/video1`. Only one gives pictures. If
Bob can't read from the first, set `device = 1` (or whichever number) under `[camera]`.

**Camera module:**
```bash
rpicam-hello --list-cameras
```
If it says "No cameras available", power off and reseat the ribbon at both ends (contacts facing the
right way, latch fully closed).

### Camera commands

| Command | Effect |
|---|---|
| `/snap` | saves a photo to `captures/` on the Pi (named by date and time) |
| `/camera off` | switches the camera off completely: nothing goes to Claude, the stream or `/snap`. On a USB camera its light should go out |
| `/camera on` | switches it back on |

To look at photos on your Mac:
```bash
rsync -av adam@bob:~/bob/captures/ ~/Desktop/bob-captures/
```

### Camera settings

| Setting | Default | What it does |
|---|---|---|
| `source` | `"auto"` | which camera to use |
| `device` | 0 | USB only: the N in `/dev/videoN` |
| `width`, `height` | 640, 480 | picture size. Bigger costs more per Claude request and runs slower |
| `jpeg_quality` | 80 | picture compression (1-100) |
| `rotate_180` | false | set `true` if the picture is upside down |
| `fov_deg` | 62.0 | the camera's horizontal field of view in degrees. Used by following and calibration, so set it right for your camera |

---

## Part 2: The video stream

While Bob runs, his camera view is available in any web browser on the same network (or over Tailscale):

| Address | What you get |
|---|---|
| `http://bob:8080/` | a simple page with the live video |
| `http://bob:8080/stream` | the raw video stream (also works in VLC) |
| `http://bob:8080/snapshot.jpg` | a single picture |

Use the Pi's Tailscale name or its IP address in place of `bob`.

**Who can watch:** with no password set, only the Pi itself (use the SSH tunnel below to see it on your
computer). To open the stream to your network, protected by a password, put a line in `.env`:

```
BOB_STREAM_TOKEN=pick-something-long
```

Then add it to the address: `http://bob:8080/?token=pick-something-long`. The password also protects the
dashboard.

**For the most privacy**, set `host = "127.0.0.1"` under `[stream]`, so the stream is only reachable through
an SSH tunnel even when a password is set:
```bash
ssh -L 8080:localhost:8080 adam@bob
```
then open `http://localhost:8080/` on your Mac.

| Setting (`[stream]`) | Default | What it does |
|---|---|---|
| `enabled` | true | the web server on or off |
| `host` | `"0.0.0.0"` | `"0.0.0.0"` = reachable on your network (but only if `BOB_STREAM_TOKEN` is set; otherwise Bob falls back to `"127.0.0.1"`); `"127.0.0.1"` = SSH tunnel only |
| `port` | 8080 | the web address port |
| `fps` | 10 | pictures per second. Lower it to save Pi CPU |
| `dashboard` | true | the phone control page (needs a password, see below) |

---

## Part 3: The phone dashboard

`http://bob:8080/dash?token=<your password>` is a control page that works on a phone, tablet or laptop.

### What's on it

- **Mode and status:** AUTO, PAUSED or E-STOP, plus the same information as the console's status bar
  (camera, mic, audio, speed cap, distance, following, cost, model).
- **A big red EMERGENCY STOP button**, always near the top.
- **The live camera view.**
- **Hold-to-drive arrows**: forward, back, spin left and right, and a stop square.
- **Buttons:** Pause AI, Resume AI, Clear E-stop, Follow me, Stop following, Mute/Unmute, Camera on/off.
- **A music card** (only when music is on): previous, play, pause, next, volume down and up.
- **A message box** to talk to Bob. Text you type is sent as `/ask` so he answers right away. Text that
  starts with `/` is sent as a command.
- **The live log**, updated every second.

### Setting it up

1. Put `BOB_STREAM_TOKEN=` followed by a password of at least 8 characters in `.env` on the Pi.
2. Restart Bob.
3. On your phone, open `http://bob:8080/dash?token=<that password>` and bookmark it.

**Without a password of 8+ characters, the dashboard stays switched off** (the plain video page still
works as before).

### How safe is it?

- **It needs the password for everything**, and checks it carefully.
- **It can only run a fixed list of commands:** stop, clear, pause, resume, step, ask, motion, camera,
  mute, follow, radio, listen, range, speed, goal, say, sound, talk, trim and music. It **can't** quit Bob,
  wipe his memory, start a calibration or change the model.
- **Hold-to-drive is fail-safe.** While you hold an arrow, the page sends a short "drive" pulse every
  quarter second, and each pulse lasts less than half a second. Let go, lose signal or close the page, and
  the wheels stop by themselves. The speed cap, obstacle reflex and emergency stop all still apply.
- **Use it over Tailscale.** On plain Wi-Fi, the password travels unencrypted, so someone on the same
  network could in principle see it. Tailscale encrypts the connection.

To switch it off: `dashboard = false` under `[stream]`.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Log says `No working camera` | check with `lsusb` / `rpicam-hello` above |
| `USB camera unavailable (can't open /dev/video0)` | try `device = 1` (or the number from `v4l2-ctl`) |
| `opened but sent no frames` | the wrong `/dev/video` node, or another program is using the camera |
| Picture upside down | `rotate_180 = true` |
| Stream page won't load | is Bob running? Is the address and port right? Is `[stream] enabled = true`? |
| `unauthorized` | the `?token=` in the address doesn't match `BOB_STREAM_TOKEN` |
| Dashboard says it's off | `BOB_STREAM_TOKEN` is missing or shorter than 8 characters, or `dashboard = false` |
| A dashboard button says it "isn't available" | that command is deliberately not allowed from the dashboard |
| Video is choppy | lower `fps`, or switch off features using CPU (the microphone, music) |
| Port 8080 already in use | another program uses it: change `port` |
