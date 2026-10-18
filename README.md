# Bob: a Claude-driven mini robot for the Raspberry Pi 4B

Bob runs entirely on the Pi. The only thing he reaches out to is the Claude API
(over Wi-Fi). Claude sees through the camera and decides every move, word and
sound. You watch and override from a live console on the Pi itself, either on
an attached screen or over SSH.

**New here? Read the manuals:** [manuals/00-START-HERE.md](manuals/00-START-HERE.md).
There is one manual for each part of Bob (hardware, console, brain, driving,
camera, voice, microphone, music, radio and more), plus a settings reference,
a safety guide and troubleshooting. This README is the shorter overview.

```
camera frame + status ──► Claude (claude-opus-5-5) ──► tools ──► servos / speaker
        ▲                                                   │
        └────────── console overrides gate every action ◄───┘
```

## Hardware

Bob supports two kinds of drive. Pick one with `type` in `config.toml`'s `[drive]` section:
`type = "dc"` (DC motors on a TB6612FNG, the default) or `type = "servo"`
(continuous-rotation servos; the servo code is still there if you switch back).

### DC motors on a TB6612FNG (`type = "dc"`)

| TB6612FNG pin | Connects to | Pi pin |
|---|---|---|
| **VM** | motor supply **+** (4.5-13.5 V: a 4xAA pack gives 6 V) | none |
| **VCC** | Pi **3.3 V** (logic power) | pin 1 |
| **GND** | motor supply **−** *and* a Pi ground | pin 34 (or any GND) |
| **STBY** | GPIO21 | pin 40 |
| **PWMA** | GPIO12 | pin 32 |
| **AIN1** | GPIO5 | pin 29 |
| **AIN2** | GPIO6 | pin 31 |
| **PWMB** | GPIO13 | pin 33 |
| **BIN1** | GPIO16 | pin 36 |
| **BIN2** | GPIO20 | pin 38 |
| **AO1 / AO2** | left motor's two wires | none |
| **BO1 / BO2** | right motor's two wires | none |

The motor supply never connects to the Pi's pins, only its ground does. Which
motor wire goes to AO1 or AO2 doesn't matter: if a wheel spins backwards on
`/fwd 1`, flip `left_invert` or `right_invert` in `config.toml`. If a motor hums
without turning at low speeds, raise `dc_min_duty`. `STBY` low cuts power to
both motors, and Bob pulls it low on an emergency stop. The PWM pins use the
Pi's hardware PWM when the overlay in "Jittery servos" below is enabled, and
fall back to software PWM otherwise (fine for motors).

### TT gear motors (the common yellow ones)

The yellow "TT" gearbox motors sold with robot-car kits suit Bob and work with
the TB6612FNG wiring above. These are typical figures; check the listing or
datasheet for yours.

| | Typical TT motor (1:48 gearbox) |
|---|---|
| Voltage | 3-6 V rated. **Don't feed it 9 V or more** |
| Speed | around 200 rpm at 6 V, with no load (a 65 mm wheel then does about 0.7 m/s, far too quick for Bob, so Bob's speed cap matters) |
| Current | roughly 150-250 mA running, **0.5-1 A or more if stalled** |
| Wires | two solder tabs (some kits include red/black leads) |

- **Supply:** a 4×AA pack (6 V; 4.8 V with rechargeables) is a good match. 2×AA
  (3 V) is too weak and won't turn the wheels under load. A USB power bank (5 V)
  also works, but the motors will be slower and weaker.
- **Current:** a TB6612FNG handles about 1.2 A per motor continuously, enough for
  TT motors. Two stalled motors can draw 2 A or more from the battery pack, which
  is another reason to keep moves short (`max_move_seconds`) and the speed cap low.
- **Higher voltage:** if you supply more than 6 V, lower `max_speed` so the
  motors aren't overdriven (about 0.6 at 9 V).
- **Solder tabs:** solder a lead to each tab, and add a 100 nF ceramic capacitor
  across the two tabs. It cuts the electrical noise the motor brushes make, which
  can disturb the Pi and the camera. It has no polarity.
- **Direction:** a TT motor mounted on each side faces the opposite way, so one
  needs to spin the other way for forward. The default `right_invert = true`
  covers this. If a wheel spins backwards, flip its `_invert` setting.
- **Tuning:** at low power TT motors typically won't start turning until the duty
  is around 0.3-0.45. Start with `/minduty 0.35`, and raise it until both wheels
  start reliably on `/move 0.05 0.05 1`. Then use `/trim` to correct drift
  (the two motors of a pair are rarely identical).
- **Jams and tipping:** if a wheel (or wheg) gets stuck, the motor pushes back on
  the body, which can tip Bob over. Mount the battery low and the motors wide
  apart, add a small skid at the back, and keep `max_speed` and
  `max_move_seconds` low so a jam only gets one short push.

### Servos (`type = "servo"`)

| Part | Connection |
|---|---|
| Left continuous-rotation servo (e.g. FS90R) | signal → **GPIO12** (pin 32) |
| Right continuous-rotation servo | signal → **GPIO13** (pin 33) |
| Servo power | separate 5 V supply (4×AA or a UBEC). **Tie its GND to Pi GND** (e.g. pin 34) |

### Everything else

| Part | Connection |
|---|---|
| Camera | Pi camera module on the CSI ribbon connector, **or** any USB webcam (UVC). Set `camera.source` in `config.toml` ("auto" tries the module, then USB) |
| Speaker | 3.5 mm jack, USB, or I²S amp. Set `audio.device` if not the default |
| Optional E-stop button | between a GPIO and GND, then set `drive.estop_button_pin` (not 5, 6, 12, 13, 16, 20 or 21) |

Don't power motors or servos from the Pi's 5 V pin. Their start-up and stall current can brown out the Pi.

In servo mode, Bob needs continuous-rotation servos. Standard 180° servos (like
the common SG90) hold an angle instead of spinning and will just twitch.

## Install (on the Pi)

```bash
cd ~/bob            # copy this folder here
./install.sh        # apt packages, pigpiod, Python venv
nano .env           # ANTHROPIC_API_KEY=sk-ant-...
```

Enable the camera if needed (`sudo raspi-config` → Interface Options), and
check it with `rpicam-hello`.

## Updating the code on the Pi

Run this on your **Mac** (not the Pi) whenever the code changes. It only sends
files that changed. Replace `adam` and the IP with your Pi's username and
address.

```bash
rsync -av --exclude '.venv' --exclude 'logs' --exclude '__pycache__' \
  ~/Documents/"Bob Cena"/ adam@192.168.x.x:~/bob/
```

The first copy works the same way. Then restart Bob so it picks up the new
code: in the console type `/quit`, then run
`cd ~/bob && .venv/bin/python bob.py` again. If Bob runs as a service, use
`sudo systemctl restart bob` instead. Re-run `./install.sh` only if
`requirements.txt` or `install.sh` changed.

Your `.env` (API key), `memory.json` and `captures/` live on the Pi only and
won't be overwritten, because they don't exist in the folder on your Mac. If
you edit `config.toml` on the Pi, a later `rsync` will replace it with the
Mac's copy, so make config changes on the Mac.

## First run: bench test with wheels off the ground

```bash
.venv/bin/python bob.py --paused
```

1. `/fwd 1`: both wheels should spin forward. If one spins backwards, flip
   `left_invert`/`right_invert` in `config.toml`.
2. `/left 0.5`, `/right 0.5`: Bob should spin in place.
3. `/say hello` and `/sound happy`: check the speaker.
4. `/snap`: saves a photo to `captures/`. Check its orientation (`camera.rotate_180`).
5. `/motion off` then `/step`: Claude runs one tick, sees, talks, and can't move.
6. `/motion on`, put Bob on the floor, `/resume`. He's on his own now.

No Pi handy? `python bob.py --sim` simulates all hardware, so you can test the
AI loop and console on any machine.

### Jittery servos

Bob drives the servos with the Pi's **hardware PWM** on GPIO12/13, which gives
steady pulses with no extra service. It needs this line in
`/boot/firmware/config.txt` (`install.sh` adds it), followed by a reboot:

```
dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4
```

At startup the log should say `Using hardware PWM on GPIO12/13`. If it says
`Hardware PWM not available`, the overlay isn't active yet. Check
`ls /sys/class/pwm/` shows `pwmchip0`. Without it, Bob falls back to pigpio (if
installed) and then to software PWM, which jitters. The overlay uses the Pi's
PWM hardware, so after enabling it re-test the headphone jack with
`speaker-test -t wav -c 2 -l 1`.

### USB camera troubleshooting

```bash
lsusb                      # is the camera listed at all?
v4l2-ctl --list-devices    # which /dev/videoN belongs to it?
```

Webcams often expose two nodes (for example `/dev/video0` for video and
`/dev/video1` for metadata). If Bob can't read frames from `video0`, set
`device = 2` (or whichever number `v4l2-ctl` shows as the capture node) under
`[camera]`. If `lsusb` doesn't show the camera, the problem is power or the
cable, not the software: try another USB port or a powered hub.

## The console

```
 BOB  AUTO | thinking | motion on | audio on | cap 0.80 | tick 12 | $0.412 | claude-opus-5-5/low
14:03:11 INFO  BOB  I see a doorway ahead. Heading over carefully.
14:03:12 INFO  MOVE L=+0.40 R=+0.40 for 1.0s
14:03:15 INFO  SAY  Oh hello! I'm Bob.
 SPACE (empty line)=E-STOP  /help  PgUp/PgDn scroll ------------------------
> _
```

- Live log tail with colours: Bob's thoughts and speech in cyan, moves in
  green, your messages in magenta, problems in yellow and red.
- Type plain text to talk to Bob. He answers out loud.
- **Space on an empty line = emergency stop.** It cuts the motors at once,
  pauses the AI, and blocks all motion until `/clear`.

| Override | Effect |
|---|---|
| `/estop`, `/clear` | lock and release the motors |
| `/pause` (or `/hush`), `/resume`, `/step` | stop Bob thinking right now (cancels the request in progress), start again, or run a single tick |
| `/ask <message>` | talk to Bob and make him answer immediately, even while paused. Plain text also reaches him, but waits for his next tick |
| `/model opus\|sonnet\|haiku` | switch Claude model live. Haiku costs about 1/40th of Opus |
| `/motion off` | AI keeps seeing and talking, but can't drive |
| `/camera off` | stop the camera sensor. No frames go to Claude or `/snap`, and Bob is told to stay put |
| `/mute` | silence all audio |
| `/drive` | manual WASD/arrow driving (Q/E arcs, X exits). Wheels stop when you let go |
| `/fwd` `/back` `/left` `/right` `/move L R S` | one-off manual moves |
| `/speed 0.4` | global speed cap |
| `/trim left 0.05`, `/trim right -0.03`, `/trim reset` | fix drift: `+0.05` makes that wheel 5% faster. `/trim` alone shows the current values |
| `/minduty 0.3` | lowest motor power that turns the wheels. Raise it if a wheel hums without turning |
| `/follow [seconds]`, `/follow off` | follow the nearest face (see "Follow me") |
| `/range`, `/range stop 25`, `/range off` | distance sensor reading, stop distance, switch the obstacle reflex off for testing |
| `/calibrate turn go`, `/calibrate straight go` | Bob measures his own turn rates and drift (pause him first) |
| `/people`, `/people forget Sam` | who Bob knows |
| `/music`, `/music pause`, `/music pair` | the Bluetooth/AirPlay speaker (see "Sound system") |
| `/listen on`, `/listen wake …`, `/talk` | microphone and wake word (see "Microphone") |
| `/radio`, `/radio log`, `/radio say …` | the Bluetooth link to John |
| `/goal …` | give Bob a new mission |
| `/notes`, `/forget` | Bob's long-term notes (`memory.json`) |
| `/effort low/medium/high` | trade reaction speed for care |

`/trim` and `/minduty` take effect immediately and are saved to `tuning.json` on
the Pi, which overrides `config.toml` at startup. The file isn't on your Mac, so
updating the code with `rsync` never overwrites it. Delete `tuning.json` to go
back to the `config.toml` values.

Overrides are checked when each action runs. Claude can't get around them, even
if he decided on a move before you pressed stop. Blocked actions come back to
him as `BLOCKED`, and he's told to stand down.

The full log is also in `logs/bob.log` (`tail -f logs/bob.log`).

## Camera stream

Bob serves live MJPEG video from the Pi, so you can watch his view in a browser
while using the console:

- `http://<pi-ip>:8080/`: viewer page
- `http://<pi-ip>:8080/stream`: raw stream (VLC, ffplay, `<img>` tags)
- `http://<pi-ip>:8080/snapshot.jpg`: one frame

`/camera off` stops the stream too. **Without a password, the stream only works on the Pi itself.** To
watch from another device, set `BOB_STREAM_TOKEN=something-long` in `.env` and open
`http://<pi-ip>:8080/?token=something-long`. Or leave the password off and view it through an SSH tunnel:
`ssh -L 8080:localhost:8080 adam@<pi-ip>`, then browse to `http://localhost:8080/`.

## Run at boot

```bash
./install.sh --service
sudo systemctl start bob
tmux attach -t bob       # open the console; Ctrl-B then D to detach
```

The service runs Bob inside a tmux session and restarts him if he crashes.

## How the brain works

Every `tick_seconds`, Bob starts a fresh, short Claude conversation: a status
report (goal, your messages, his recent actions, his saved notes) plus a camera
frame. Claude calls tools (`drive`, `set_wheels`, `stop`, `look`, `speak`,
`play_sound`, `wait`, `remember`), at most 8 rounds, then ends the tick. Fresh
conversations keep each request small. `remember` lets him learn across ticks
and reboots, for example "a 0.5 s spin at 0.6 turns about 90°".

Safety rails in code (Claude can't exceed these): a speed cap, a 3 s maximum
per move, and a watchdog that stops the wheels when any move's time runs out.
Server-side refusal fallback is on (`brain.fallbacks`), so if a request is ever
declined, the API retries it on another model instead of stalling.

## Cost

Opus with a camera frame every few seconds adds up. Expect a few cents per
tick, which can reach tens of dollars per hour of continuous autonomy. The
status bar shows a running estimate. To spend less, raise `tick_seconds`, or
set `model = "claude-sonnet-5-5"` or `"claude-haiku-5-5"` in `config.toml`.

## Sound system (Bluetooth and AirPlay)

Bob can be a speaker. Play music from a phone or Mac over Bluetooth or AirPlay and it comes out of Bob's
speaker, shared with his own voice:

- **One mixer for everything.** Bluetooth, AirPlay and Bob's voice all play into PipeWire, the Pi's audio mixer,
  so they blend instead of fighting for the speaker.
- **Bob's voice ducks the music.** While he talks, the music fades to a quarter of its volume, then returns a moment
  after he stops (not between his sentences).
- **Newest source wins.** If you start AirPlay while Bluetooth is playing, the Bluetooth music is paused
  (through the phone's own remote control; if that isn't possible, its stream is muted until AirPlay stops).
- **The microphone ignores the music**, so lyrics aren't transcribed and can't trigger the wake word
  (`mic_deaf_while_playing`). Push-to-talk still works.
- **Bob can control it.** Claude has a `music` tool: play, pause, next, previous, volume up or down, set volume, and
  what's playing. He can only control music a person is streaming, can't start music himself, and is told to keep
  the volume modest and not to interrupt music people are enjoying. The volume has a ceiling (`max_volume`, 85%).
  Song titles are shown to him as plain information, never as instructions.

**Setup (once, on the Pi).** Read what it changes first: it installs PipeWire, BlueZ and shairport-sync, turns on
"linger" for your user, and runs the AirPlay receiver as *your* user service (required with PipeWire).

```bash
cd ~/bob
./install_music.sh            # explains what it will do, then asks
```

Then in `config.toml` set `[music] enabled = true`, copy it over with `rsync`, and restart Bob. The log says if
anything is missing, and `/music` lists the problems. Pi OS **Lite** usually doesn't include PipeWire (the script installs it); Pi OS with a desktop usually
already has it.

**Using it.**
- **Bluetooth:** in Bob's console type `/music pair`. For two minutes the Pi is discoverable; on the phone choose
  "Bob" in Bluetooth settings. Bob trusts the phone, so afterwards it should reconnect by itself (that part is up to the
  phone) and the Pi goes back to being invisible. `/music devices` lists paired phones and `/music forget AA:BB:CC:DD:EE:FF` removes one.
- **AirPlay:** nothing to set up. Choose "Bob" in the AirPlay menu on an iPhone or Mac on the same Wi-Fi.
- Every new music stream starts at `initial_volume` (50%), so a phone left at full volume isn't deafening.

| Command | Effect |
|---|---|
| `/music` | what's playing, the volume, and any problems |
| `/music play`, `pause`, `next`, `prev` | press the buttons on whatever is playing |
| `/music vol 40`, `vol up`, `vol down` | set or nudge the volume (capped at `max_volume`) |
| `/music pair [seconds]` | open Bluetooth pairing for a short time (default 120 s) |
| `/music devices`, `/music forget MAC` | list or remove paired Bluetooth devices |
| `/music ai off` | take the music controls away from Claude |

The dashboard has a music card with the same buttons.

**Security.**
- Bluetooth is only pairable while you have pairing open. After that only phones you paired can connect.
  Anyone who is paired can play audio through Bob and press his play/pause, so `forget` phones you no longer trust.
- **AirPlay is open to everyone on your Wi-Fi** unless you set a password: re-run the script with
  `BOB_AIRPLAY_PASSWORD='something' ./install_music.sh`. (The password sits in `~/.config/shairport-sync.conf`,
  readable only by you.)

**What I could and couldn't test.** Everything above was tested here only against stand-ins that imitate PipeWire,
BlueZ, shairport-sync and `bluetoothctl` (the volume, ducking, newest-wins, pairing and control logic, and the
install script's behaviour in a sandbox). **None of it has run on a real Pi with a real phone.** Expect to fiddle.
Things to know:
- **Remote control depends on the phone.** Bluetooth play/pause/next works if the phone exposes a media player
  (nearly all do). AirPlay play/pause works only if the sender allows remote control (iPhones and Macs normally do).
  If not, Bob says so and suggests using the phone. Volume still works either way, since Bob adjusts his own
  mixer, not the phone.
- **AirPlay here is classic AirPlay (the original protocol).** It works from iPhone and Mac, but it isn't AirPlay 2:
  no multi-room, and not every app offers it. The distribution's shairport-sync may lack the D-Bus interface Bob
  uses for remote control; the install script warns if so. Bob can still hear AirPlay start and stop and duck it, but
  can't press its buttons. The project's build instructions ([shairport-sync BUILD.md](https://github.com/mikebrady/shairport-sync/blob/master/BUILD.md))
  cover building one with PipeWire and D-Bus support.
- **Bluetooth, Wi-Fi and Bob's radio to John share the Pi 4's one antenna.** If music stutters, use 5 GHz Wi-Fi,
  and turn off the radio link while testing.
- **The microphone and PipeWire.** If the USB microphone says "device busy" after installing PipeWire, set
  `[mic] device = "pipewire"` (it records through PipeWire instead of grabbing the card directly).
- **Wrong speaker?** `wpctl status` lists outputs; `wpctl set-default <id>` picks one.

**Undo.** `./install_music.sh --undo` removes the AirPlay receiver and its settings. Set `[music] enabled = false`
to switch Bob's music features off. PipeWire and Bluetooth are left as they were.

## Distance sensor (HC-SR04)

An ultrasonic sensor facing forward gives Bob a reflex that works whatever Claude decided: the wheels
refuse to drive forward into anything closer than `stop_cm` (15 cm), and a forward move already under
way is cut off the moment something comes inside that distance. Turning and backing up are always
allowed. Claude is also told the distance in every status report and after each move.

**Wiring. The ECHO pin outputs 5 V, which can damage a Pi pin, so divide it down:**

| Sensor pin | Connects to |
|---|---|
| VCC | 5 V (the motor-supply 5 V rail is fine) |
| GND | ground (common with the Pi, as with everything else) |
| TRIG | GPIO23 (pin 16) |
| ECHO | **1 kΩ resistor to GPIO24 (pin 18), and GPIO24 to ground through a 2 kΩ resistor** |

Then set `[sensor] enabled = true`. In the console, `/range` shows the reading, `/range stop 25`
changes the stop distance, and `/range off` disables the reflex for testing. It sees a narrow cone
straight ahead, so it can miss thin, soft or angled objects: it backs up the camera, it doesn't replace it.
A disconnected sensor reads as "clear", so check `/range` with your hand in front of it.

## Follow me (person following)

`/follow` (or "follow me", or Claude's `follow_person` tool) makes Bob turn toward the nearest face and
keep about a metre away. Claude thinks every few seconds, which is too slow to follow someone smoothly,
so while following a small face detector on the Pi steers the wheels about 8 times a second and Claude is
simply told how it went. Everything runs on the Pi.

- It follows **faces**, so it works while the person faces Bob, and loses them when they turn away
  (he turns toward where he last saw them for a moment, then gives up after `lost_after_s`).
- He never reverses blindly, never closes in on something inside 40 cm, and every steering command
  expires in a fraction of a second, so a stalled loop stops the wheels. The distance sensor, the speed
  cap, `/pause` and the emergency stop all work during a follow.
- `/follow 20` follows for 20 s, `/follow off` stops. Detection range is roughly 2 m.
- Tune it in `[follow]`: `distance_m`, `max_speed`, `turn_gain` (lower it if he swings left and right),
  `forward_gain`. Set `camera.fov_deg` to your camera's real field of view (Camera Module v2 is 62).
- `install.sh` downloads the YuNet face model into `models/`. Without it Bob falls back to OpenCV's older
  built-in detector, which is less reliable.

`/find` makes Bob turn slowly on the spot until he sees a face (he never drives forward doing it), then
greet them. Claude has the same ability as the `find_person` tool. Tune it with `scan_speed` and
`scan_seconds` in `[follow]`.

## Checking on Bob

`/check` prints one report: motors, camera (it takes a picture), speaker, microphone, distance sensor,
stream, API key, music, radio, plus the Pi's temperature, power supply, disk space, memory and Wi-Fi. It
moves nothing and costs nothing.

`/timeline on` records what Bob saw, decided and did (ticks, tool calls, stop reasons, operator commands)
to `logs/timeline/`, with small camera pictures. It's off by default, deletes records after `keep_days`, and
`/timeline clear` wipes it. The pictures can show people. See `[timeline]` in `config.toml`.

`/search WORDS` searches everything Bob has recorded (timeline, notes, people, radio, warnings, the manuals)
through a small SQLite index in `logs/index.db`, for example `/search kind:estop since:yesterday`. It reads
only new records, follows deletions (`/timeline clear` removes the matching rows), and can be rebuilt any
time with `/index rebuild`. With `/index ai on`, Claude can search his own past too (off by default).

## Remembering people

Claude has a `remember_person` tool (name, how to recognise them, notes) and sees the list every tick, so he
can greet people by name. It is stored in `people.json` on the Pi only. He is told to use only names people
give him, not to guess identities from looks, and not to store sensitive details. `/people` lists everyone,
`/people forget Sam` removes one person, and `/people clear` wipes the list. The list is capped at 30 people
(the one not seen for longest is dropped to make room). The list is sent to Claude as text on every tick.

## Self-calibration

Bob can measure his own motion with the camera. Pause him first, point him at a room with some detail in view
(not a blank wall), and type:

```
/calibrate turn           shows what will happen; add "go" to start
/calibrate turn go        spins left and right a few times, measures how far he really turned
/calibrate straight go    drives about half a metre forward and back, twice, and works out a /trim to cancel drift
/calibrate show           the saved results; /calibrate cancel stops a run
```

- **Turn rates** are saved and shown to Claude ("at speed 0.7 you turn about 75 degrees a second"), so he
  can plan a 90-degree turn instead of guessing. They are measured at the current `/speed` cap; if you
  change the cap later Claude is told they may be off.
- **Straight** sets `left_trim`/`right_trim` and saves them, the same values `/trim` uses.
- It compares the pictures before and after each move, using the camera's field of view
  (`camera.fov_deg`). In a simulation it measured turns to within 0.3% and the drift correction to
  within 0.001, but a real room, a wobbly robot and real wheels will be less tidy: run it twice and see
  if the numbers agree. If the scene lacks detail or the move is stopped early it says so and changes nothing.
- It is operator-only (Claude can't start it) and refuses to run while the AI is running or the emergency stop is on.

## Phone dashboard

`http://<pi>:8080/dash?token=<your password>` is a control page for your phone or laptop: live video,
a big emergency-stop button, hold-to-drive arrows, pause/resume, follow, mute, camera on/off, a box to
talk to Bob, and the live log with the status line.

- **It needs a password.** Set `BOB_STREAM_TOKEN` (8+ characters) in `.env`. Without one the dashboard
  stays off (the camera page behaves as before). Use it over Tailscale, which encrypts the connection;
  on plain Wi-Fi the password travels unencrypted.
- It can only run a fixed list of commands: stop, pause/resume, follow, mute, camera, speed, trim, say, ask,
  motion, radio, listen, range, goal. It can't quit Bob, wipe his memory or start a calibration.
- Hold-to-drive sends a short pulse every quarter second; let go (or lose signal) and the wheels stop by
  themselves within half a second. The obstacle reflex and emergency stop apply.
- Turn it off with `dashboard = false` under `[stream]`.

## Talking to John (Bluetooth radio)

Bob can chat with another robot (a friend's, called John) over Bluetooth. Claude
gets a `radio_send` tool, and John's messages show up in Bob's status report. You
can watch every message from the console. Everything stays between the two Pis.

**Set up (once, on both Pis):**

1. Pair them so the link is encrypted. On each Pi run `sudo systemctl enable --now bluetooth`.
   Find Bob's address with `bluetoothctl show` (the `Controller AA:BB:...` line). On Bob run
   `bluetoothctl`, then `power on`, `agent on`, `default-agent`, `discoverable on`, `pairable on`.
   On John's Pi run `bluetoothctl`, then `power on`, `agent on`, `default-agent`, `scan on`,
   and when Bob's address appears: `pair <address>`, confirm the code on both sides, then
   `trust <address>`.
2. Make a shared secret and put it in `.env` on **both** Pis, the same text on each:
   `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`, then
   `BOB_RADIO_SECRET=<that text>`. Exchange it privately (not by pasting it in chat).
   Every message is signed with it, so a stranger who connects can't talk to Bob.
3. In `config.toml` set `[radio] enabled = true`. Bob keeps `role = "listen"`;
   John uses `role = "connect"` with `peer_address` set to Bob's address.
4. Restart Bob. The log shows `Radio: waiting for John` and then `Radio: linked with John`.

Give your friend [JOHN_PROMPT.md](JOHN_PROMPT.md). It's written to be pasted into their
existing chat with Claude, and includes the message format, test values, safety rules and
the complete radio code, so John's radio will be compatible with nothing else to send.

**Watching and controlling it from the console:**

| Command | Effect |
|---|---|
| `/radio` | link state, message counts, and whether Claude may send |
| `/radio log 20` | the last 20 messages with times and direction |
| `/radio say hello John` | send a message yourself, as the operator |
| `/radio ai off` / `on` | stop or allow Claude sending (he's told the radio is off) |
| `/radio off` / `on` | drop the link / reconnect |

Messages also appear live in the log as green `RADIO Bob -> John: ...` lines, and
are saved to `logs/radio.jsonl`.

**Safety and cost:**

- John's messages reach Claude as quoted, untrusted text. Bob is told that John
  can't give him orders or override you, and newlines are stripped so a message
  can't pose as "Operator says:". Nothing from the radio can move the wheels directly.
- Two Claudes could chat forever, and every message costs money. Claude is limited to
  `ai_max_per_minute` messages (6), the system prompt asks him to stop when the
  conversation is over, and `/radio ai off`, `/pause` and `/estop` silence him at once.
- The Bluetooth part is the least tested piece: the protocol, signing and link logic
  were tested over ordinary network sockets here, not over real Bluetooth. If the two
  Pis don't link, check pairing first (`bluetoothctl devices`) and that both use the same
  `channel`, then paste the `Radio:` log lines.

## Microphone (talk to Bob)

Plug in a USB microphone and Bob can hear you. Speech is turned into text **on
the Pi** by [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (the
`tiny.en` model), then handed to Claude as if you'd typed it, and Bob answers
out loud. The transcript appears in the log as `HEARD ...`.

**Set up:**

```bash
arecord -l                      # find the microphone: "card 1, device 0" means plughw:1,0
arecord -D plughw:1,0 -d 3 -f S16_LE -r 16000 test.wav && aplay test.wav   # record 3 s and play it back
```

Put the device in `config.toml` under `[mic]` (`device = "plughw:1,0"`), then in
the console:

```
/listen on                 start the microphone
/listen                    show status and the live loudness level
```

**Wake word.** In hands-free mode Bob ignores speech until he hears a wake word, then listens for
`wake_window_s` (20 s) without needing it again. By default this uses
[openWakeWord](https://github.com/dscripka/openWakeWord), a small audio model that runs on the Pi, so
nothing is sent to Whisper (or transcribed at all) until the wake word is heard. Its pretrained words are
"hey jarvis", "alexa", "hey mycroft" and "hey rhasspy"; **the default is "hey jarvis"** because
there is no pretrained "hey Bob". To get your own, train one with openWakeWord's Colab notebook, save the
`.onnx` file as `wakewords/hey_bob.onnx`, and set `wake_model = "wakewords/hey_bob.onnx"`. Say the wake word
and the command in one breath ("Hey Jarvis, what do you see?") or say it alone and wait for the chirp.
**The included "hey bob" model is a small, home-trained one.** In tests with computer-generated voices it
heard a plain "Hey Bob" nearly every time, but it also woke to look-alikes ("Hey Rob", "Hey Bobby", "Hey Boss",
"Hey Mom"), missed some pauses and longer phrases, and did badly in background noise. So `wake_confirm = true`
makes Bob double-check: after the model fires, the first thing he hears is transcribed and must contain
"Bob" (loosely: "Bub" or "Bop" pass, "Rob" or "Boss" don't), or the wake is cancelled. That costs one quick
transcription on a false wake. Real voices and rooms will differ from my tests, so try it and adjust
`/listen wake threshold`. "Hey Jarvis" (`wake_model = "hey_jarvis"`) was more reliable, if you want a safer fallback.
Settings: `/listen wake` shows the state, `/listen wake text` matches the word "bob" in the transcript instead
(no extra install, but everything you say gets transcribed), `/listen wake off` reacts to everything,
`/listen wake threshold 0.7` makes it harder to trigger by accident. To get a better "hey bob" than the downloaded one, see [TRAINING_HEY_BOB.md](TRAINING_HEY_BOB.md) (how to retrain it, and `wakeword_tools.py` to record your own voice and score models). Push-to-talk never needs a wake word.

**Spoken commands.** A few short phrases are handled at once, without waiting for Claude: "follow me" /
"come here" start following, and "stop" / "freeze" / "stay" stop Bob and pause the AI. Only an utterance
that is exactly one of these counts. Don't rely on voice to stop a moving robot: the microphone is
deliberately deaf while the wheels turn, so "stop" is heard only when he is idle. Use Space, `/estop`, the
dashboard button or a physical button.

**Two modes** (`mode` in `[mic]`, or `/listen mode ptt|hands-free` live):

- **hands-free:** just talk. Bob cuts what he hears into sentences by loudness.
  If it triggers on background noise, or misses your voice, run `/listen`, watch
  the level while you talk and while it's quiet, and set `/listen threshold` between
  the two (default 0.02).
- **push-to-talk:** press **Tab** (or type `/talk`) to start recording and again to
  send. Nothing is recorded in between. Bob answers right away, even while paused.

**Good to know:**

- **Bob won't hear himself.** The microphone is deaf while the speaker plays and for
  `after_speech_s` afterwards, and (by default) while the wheels turn, since motor
  noise becomes garbage text. Keep the microphone away from the motors and the speaker.
- **It's off at boot** unless you set `enabled = true`, because it is an
  always-on microphone. `/listen off` stops it completely. Your words are sent to
  Claude as text (not audio), like anything you type.
- **Accuracy and speed.** `tiny.en` is fast but makes mistakes, especially with
  names and in noisy rooms. For better results set `model = "base.en"` (slower).
  The first use downloads the model (about 75 MB), and `install.sh` does this for you.
  Transcription time on a Pi 4 depends on how busy it is, so turn off the camera
  stream while testing if it feels slow.
- **Not installed?** `/listen on` tells you what is missing. To add it by hand:
  `.venv/bin/pip install faster-whisper`.

## Voice (Piper)

Bob speaks with [Piper](https://github.com/OHF-Voice/piper1-gpl), an offline
neural voice that runs on the Pi and sounds far more natural than espeak. If
Piper isn't installed or fails, he falls back to espeak-ng automatically.

`install.sh` installs it and downloads the `en_US-lessac-medium` voice into
`voices/`. To install it by hand:

```bash
cd ~/bob
.venv/bin/pip install piper-tts
.venv/bin/python -m piper.download_voices --data-dir voices en_US-lessac-medium
```

The startup log should say `Speech engine: piper`. Test it with `/say hello`.

- **Speed:** Bob loads the voice once at startup (the log says `Piper voice
  loaded`) and speaks sentence by sentence, so the first sentence starts playing
  while the rest is still being generated. Each utterance logs
  `Spoke with piper: first audio after Xs, done in Ys`, so you can see how long
  it takes on your Pi.
- **Still slow?** If the first audio takes more than a second or two, or there are
  gaps between sentences, the voice is too heavy for the Pi. Use the smaller
  `en_US-lessac-low`: download it with
  `.venv/bin/python -m piper.download_voices --data-dir voices en_US-lessac-low`
  and set `piper_model = "en_US-lessac-low"` under `[audio]`. Turning off the
  camera stream and the microphone frees CPU too, and shorter sentences from Bob
  help as well.
- **Other voices:** list them with `.venv/bin/python -m piper.download_voices`.
- **A voice file elsewhere:** set `piper_model` to the path of a `.onnx` file.
- **Back to espeak-ng:** set `tts = "espeak-ng"`.

# Built With
![Claude Code](https://img.shields.io/badge/Claude%20Code-%23D97757.svg?style=for-the-badge&logo=claudecode&logoColor=white) 
![Claude](https://img.shields.io/badge/claude-%23D97757.svg?style=for-the-badge&logo=claude&logoColor=white)
![Tinkercad](https://img.shields.io/badge/Tinkercad-%231477D1.svg?style=for-the-badge&logo=tinkercad&logoColor=white)
![Raspberry Pi](https://img.shields.io/badge/Raspberry_Pi-1000?style=for-the-badge&logo=raspberrypi&logoColor=ffffff&labelColor=A22846&color=a22946)
![Google Colab](https://img.shields.io/badge/Google%20Colab-%23F9A825.svg?style=for-the-badge&logo=googlecolab&logoColor=black)
![OpenCV](https://img.shields.io/badge/opencv-%23fff.svg?style=for-the-badge&logo=opencv&logoColor=black)
## Tests

A few checks for the safety-critical bits (settings validation, damaged memory files, the dashboard's
request checks) run without any hardware:

```bash
python3 -m unittest discover -s tests
```

(They need the `anthropic` package: run them inside the Pi's `.venv`, with `.venv/bin/python -m unittest discover -s tests`.)
