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
| The video stream | anyone on your Wi-Fi, by default | set `BOB_STREAM_TOKEN` |
| The dashboard | only with the password | 8+ character `BOB_STREAM_TOKEN`; use it over Tailscale |
| Bluetooth pairing | only during `/music pair` (2 minutes) | `/music forget` old phones |
| AirPlay | everyone on your Wi-Fi, by default | `BOB_AIRPLAY_PASSWORD` when installing |
| The radio | only a robot with the shared secret | `BOB_RADIO_SECRET` |
| What Claude sees | camera pictures, transcripts, notes, people list | `/camera off`, `/listen off`, `/forget`, `/people clear` |

Keep `.env` private. It holds your API key, which spends your money.

## Cost safety

An unattended running Bob keeps spending. The status bar shows a running estimate. Set a monthly spending
limit in your Anthropic account, `/pause` whenever you're not watching, and use Haiku for testing.
