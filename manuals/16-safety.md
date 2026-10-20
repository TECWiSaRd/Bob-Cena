# Manual 16: Safety

Bob is small, but he's a moving machine with batteries, driven by an AI that can make mistakes. This
manual gathers every safety feature in one place, and gives a checklist for running him.

---

## Every way to stop Bob

| Method | Where | Stops | Notes |
|---|---|---|---|
| **Space** on an empty input line | console | everything that moves; pauses the AI | press Esc first if you've typed something |
| `/estop` | console | same as Space | |
| **EMERGENCY STOP** button | phone dashboard | same as Space | needs the dashboard set up |
| Physical button | on Bob (optional) | same as Space | wire one to GPIO26 ([manual 01](01-hardware-and-wiring.md)) |
| `/pause` | console or dashboard | Claude's thinking, the current request, the wheels, following | not a lock: you can still drive by hand |
| Say "stop" | microphone | the wheels, following, the AI | **only works while he's standing still** |
| `/shutdown` then `/shutdown confirm` | console, shared console, dashboard button | everything: Bob quits cleanly and the Pi powers off. **It cannot be switched back on from a distance** | two steps, by the same person |
| Pull the motor battery | on Bob | all motor power | the last resort; always works |

**What the emergency stop does:**
1. Stops both wheels immediately.
2. Switches off the motor driver board (its STBY pin), cutting power to both motors.
3. Pauses the AI and cancels any request in progress.
4. Ends any follow and blocks calibration.
5. **Refuses every movement** (from Claude, you, the dashboard or following) until you type `/clear`.

The status bar turns red and shows `E-STOP`. After `/clear`, the AI stays paused until you `/resume`.

It **doesn't** silence Bob. Use `/mute` for that.

## Safety built into the code

These work whatever Claude decides. He can't switch them off.

| Protection | What it does |
|---|---|
| **Speed cap** | every movement is scaled by `max_speed` (0.8; `/speed` to change) |
| **Move time limit** | no single movement lasts more than 3 s (`max_move_seconds`) |
| **Watchdog** | checks 50 times a second and stops the wheels when a move's time is up, even if the program freezes |
| **Overrides checked at the last moment** | stop, motion off, camera off and mute are checked right before each action, so a decision Claude made earlier can't sneak through |
| **Obstacle reflex** | with the distance sensor, refuses or stops forward moves inside 15 cm |
| **Follow-me limits** | never reverses blindly; won't close in inside 40 cm; each steering command expires within half a second |
| **Dashboard drive pulses** | each lasts under half a second, so losing signal stops the wheels |
| **Clean shutdown** | quitting, crashing or stopping the service stops the wheels and switches off the motor driver |
| **API outage** | if the internet drops, Bob stops the wheels before retrying |
| **Untrusted text** | song titles and messages from John are passed to Claude as information, never instructions |

## Things NOT to rely on

- **Your voice, to stop him while he's moving.** The microphone is deaf while the wheels turn.
- **The distance sensor, for everything.** It sees a narrow cone straight ahead. It misses thin legs, soft
  fabric, angled surfaces, and it can't see drops (stairs, table edges).
- **The camera, for drops.** It points forward, so it barely sees the floor right in front of him.
- **Claude, to always be right.** He's told to be careful, but AI models can misjudge distances or misread a
  scene. That's why the hard limits above exist.

## Before a run: checklist

- [ ] **Floor:** open space, no stairs, no table edges, no cables, no liquids, nothing fragile.
- [ ] **People and pets:** they know Bob is moving. Small children and pets supervised.
- [ ] **Batteries:** charged, correctly inserted, not hot.
- [ ] **Wiring:** nothing loose; no bare wires touching ([manual 01](01-hardware-and-wiring.md)).
- [ ] **Bench test** with the wheels off the ground: `/fwd 1`, `/left 0.5`. Wheels go the right way.
- [ ] **Speed:** start low, `/speed 0.4`, for a first run anywhere new.
- [ ] **Model:** `/model haiku` while testing, to keep costs down.
- [ ] **Stop ready:** the console open with an empty input line, or the dashboard open, or a physical button.
- [ ] **Notes:** check `/notes` for anything stale.

Then put him on the floor and type `/resume`.

## During a run

- Stay within reach, or within sight of a stop button.
- Watch the log: `BOB` lines say what he's planning.
- If he heads somewhere he shouldn't: **Space** first, think later.
- If anything smells hot or smokes: **Space**, then pull the motor battery, then unplug the Pi.

## After a run

- `/pause` before you walk away. A running Bob keeps driving and spending money.
- `/quit` to shut down, or leave him paused in tmux.
- Take the motor batteries out if he'll sit unused for a while.

## Electrical safety

- **Separate power, shared ground.** Motors on their own battery, Pi on its own supply, grounds connected.
- **`/locate` and `find_my_room` turn the whole robot on the spot** for up to 25 seconds (a wide sweep). They
  obey `/motion off`, `/pause` and the emergency stop, and never drive forward. Clear the area first.
- **Lights are the only thing Bob can control in your home** (see [Home Assistant](19-home-assistant.md)). He
  can't unlock doors, change the heating or touch anything else, whatever Claude decides.
- **Never** power motors or servos from the Pi's 5 V pins: they can reboot or damage the Pi.
- **Red to +, black to −** on every power connection. Reversing one can destroy a board.
- **The distance sensor's ECHO pin needs its voltage divider.** 5 V can damage a Pi pin.
- **Stalled motors draw a lot of current** and get warm. Keep moves short and the speed cap modest.
- Don't mix old and new batteries, or different types.
- Wire with everything switched off. Connect the motor battery last.

## Privacy and security

| Thing | Who can reach it | Protection |
|---|---|---|
| The console | anyone who can SSH into the Pi | your Pi password; Tailscale |
| The video stream | only the Pi itself, until you set `BOB_STREAM_TOKEN`; then anyone with the password | `BOB_STREAM_TOKEN` |
| The dashboard | only with a token | `BOB_STREAM_TOKEN` (yours), or a personal `TOKEN_NAME` that only works on its own Wi-Fi network; 8+ characters; wrong guesses are locked out; use it over Tailscale |
| Bluetooth pairing | only during `/music pair` (2 minutes) | `/music forget` old phones |
| AirPlay | everyone on your Wi-Fi, by default | `BOB_AIRPLAY_PASSWORD` when installing |
| The radio | only a robot with the shared secret | `BOB_RADIO_SECRET` |
| Home Assistant | anyone with `HA_TOKEN` | token only in `.env`; Bob can only switch lights, only in listed rooms, only the room he's in, with quiet hours, a cooldown and a rate limit; `/home ai off` |
| Powering the Pi off | owners, operators and dashboard users (not viewers) | two steps by the same person; Claude has no way to do it; `[power] who` |
| The shared console | members of the `bobops` / `bobview` groups | Linux identifies each person; no shell; operators can't `/quit`; viewers can only watch and press the emergency stop; everything is recorded by name |
| The search index | anyone who can log in to the Pi | it holds copies of notes, people and timeline text; it follows deletions; `enabled = false` turns it off |
| Claude searching his history | only if `/index ai on` | off by default; timeline and radio records only, shown to him as data |
| The timeline (if on) | anyone who can log in to the Pi | off by default; `thumbnails = false`; `/timeline clear` |
| What Claude sees | camera pictures, transcripts, notes, people list | `/camera off`, `/listen off`, `/forget`, `/people clear` |

Keep `.env` private. It holds your API key, which spends your money.

## Cost safety

An unattended running Bob keeps spending. The status bar shows a running estimate. Set a monthly spending
limit in your Anthropic account, `/pause` whenever you're not watching, and use Haiku for testing.
