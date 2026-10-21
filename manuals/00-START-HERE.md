# Bob: start here

Bob is a small robot built on a Raspberry Pi 4B. A Claude AI model is his mind: it looks through his
camera, decides where to drive, what to say and which sounds to make, and talks to people. Everything
else runs on the Pi itself. The only thing Bob reaches out to is the Claude API, over Wi-Fi.

You stay in charge from a **console**: a text screen on the Pi that you open over SSH. It shows what Bob
is thinking and doing, and lets you stop, pause or drive him at any moment.

This folder has one manual for each part of Bob. Each manual is written so you can read it on its own.

---

## The manuals

| # | Manual | Read it when you want to... |
|---|---|---|
| 00 | **Start here** (this page) | get the big picture and a daily routine |
| 01 | [Hardware and wiring](01-hardware-and-wiring.md) | build or rewire Bob, check a pin, choose batteries |
| 02 | [Installing and updating](02-installing-and-updating.md) | set up a Pi, copy new code, start Bob at boot |
| 03 | [The console](03-console.md) | learn the screen, the keys and every command |
| 04 | [The brain (Claude)](04-brain-and-claude.md) | understand how Bob thinks, what he sees, what it costs |
| 05 | [Driving and motors](05-driving-and-motors.md) | drive by hand, set speed limits, fix a wheel |
| 06 | [Calibration](06-calibration.md) | make Bob drive straight and turn accurately |
| 07 | [Camera, stream and dashboard](07-camera-stream-and-dashboard.md) | see what Bob sees, use the phone control page |
| 08 | [Follow me](08-follow-me.md) | have Bob follow a person |
| 09 | [Distance sensor](09-distance-sensor.md) | add the ultrasonic "don't hit things" reflex |
| 10 | [Voice and sounds](10-voice-and-sounds.md) | change how Bob speaks, fix slow or missing speech |
| 11 | [Microphone and wake word](11-microphone-and-wake-word.md) | talk to Bob out loud, tune "Hey Bob" |
| 12 | [Sound system (Bluetooth and AirPlay)](12-sound-system.md) | play music through Bob from a phone |
| 13 | [Radio to John](13-radio-to-john.md) | let Bob talk to your friend's robot |
| 14 | [Memory and people](14-memory-and-people.md) | see or wipe what Bob remembers |
| 15 | [Settings reference](15-settings-reference.md) | look up any setting in `config.toml` or `.env` |
| 16 | [Safety](16-safety.md) | know every way to stop Bob, and a pre-run checklist |
| 17 | [Troubleshooting](17-troubleshooting.md) | fix something that isn't working |
| 18 | [Resources](18-resources.md) | find links, file lists, parts info and cheat sheets |
| 19 | [Home Assistant](19-home-assistant.md) | let Bob turn the lights on and off in his room |
| 20 | [Shared console](20-shared-console.md) | let friends with their own Pi login use the same console |
| 21 | [Powering off](21-powering-off.md) | shut the Pi down safely, from the console or the dashboard |
| 22 | [Xbox controller](22-xbox-controller.md) | drive Bob with a game controller |

Two more guides live in the main project folder:
- [TRAINING_HEY_BOB.md](../TRAINING_HEY_BOB.md): training a better "Hey Bob" wake word.
- [JOHN_PROMPT.md](../JOHN_PROMPT.md): the message to give your friend for John's radio.

---

## If you're running Bob but didn't build him

You don't need to read all twenty-two manuals. Read this page, then [the console](03-console.md) and
[Safety](16-safety.md) (about fifteen minutes in total). Use the rest when you need them.

**What to ask the owner for first:**
1. **How to reach the Pi:** its name or address (such as `bob`, or `192.168.x.x`), the username, and the
   password. The manuals use `adam` and `bob` as examples; use the real ones.
2. **That Bob has an API key set up** (`ANTHROPIC_API_KEY` in `.env` on the Pi). Without one, Bob can move
   when you drive him but can't think.
3. **Who pays for Claude.** Each hour of Opus thinking costs real money (see
   [the brain](04-brain-and-claude.md)). Agree on `/model haiku` for testing and `/pause` when you walk away.
4. **Which parts have been checked** (the last section on this page), so you know what to expect.

**Connecting from a Windows PC:** open **Windows Terminal** or PowerShell and type the same
`ssh username@address` as the examples. SSH is built into Windows 10 and 11. (`rsync`, used to copy new
code, isn't; only the person who maintains Bob's code needs it.)
**From a phone:** if the owner has set up the dashboard, you can use that instead
([manual 07](07-camera-stream-and-dashboard.md)).

**Your first session, step by step:**
1. Check the floor is clear and the motor batteries are in. Read the checklist in [Safety](16-safety.md).
2. Connect with SSH. If Bob is already running (the owner may have set him to start at boot), type
   `tmux attach -t bob`. If not, follow the routine below.
3. Look at the top status bar. If it says `PAUSED`, he won't move on his own.
4. Say hello: `/ask hello Bob`. He answers out loud and in the log.
5. Try `/drive` and use W/A/S/D, with the wheels off the ground. X leaves drive mode.
6. When you're ready, put him on the floor and type `/resume`. **Space** stops him at any time.
7. `/pause` before you walk away.

Keep the owner's phone number handy: if something smells hot or Bob behaves badly, **Space**, then pull the
motor battery.

---

## How Bob fits together

```
                       ┌──────────── you: console (SSH) or phone dashboard ────────────┐
                       │      stop, pause, drive, talk, change settings, watch          │
                       ▼                                                                 │
  camera ─┐       ┌──────────┐      tools: drive, look, speak, follow,      ┌──────────┐ │
  mic ────┼─────► │  Claude  │ ───► music, remember, radio ...  ──────────► │  motors  │ │
  sensor ─┤       │ (brain)  │      every action is checked against         │  speaker │ │
  radio ──┘       └──────────┘      your overrides before it happens        └──────────┘ │
                       ▲                                                                 │
                       └──────────────── log of everything he does ──────────────────────┘
```

- **Claude runs in short rounds called ticks.** Every couple of seconds, Bob sends Claude a status report
  and a camera picture. Claude decides what to do, using "tools" (drive, look, speak and so on), then the
  round ends. See [the brain manual](04-brain-and-claude.md).
- **Your overrides always win.** Every action Claude asks for is checked against your settings right
  before it happens. If you've pressed stop, turned motion off or muted him, the action is refused.
- **Safety limits are built into the code**, so Claude can't exceed them: a speed cap, a maximum
  length for each move, and a watchdog that stops the wheels when a move's time runs out.

## Your daily routine

1. **Power up.** Batteries for the motors, then USB-C power for the Pi.
2. **Connect.** From your computer: `ssh adam@bob` (use your own username and the Pi's name or address;
   see [installing](02-installing-and-updating.md)).
3. **Start Bob paused**, so nothing moves until you say so:
   ```bash
   cd ~/bob
   tmux new -s bob
   .venv/bin/python bob.py --paused
   ```
4. **Quick check.** Type `/check` for a one-screen report (anything marked `FAIL` needs fixing; `WARN`
   deserves a look). Then, with the wheels off the ground the first time each day: `/fwd 1`, `/left 0.5`,
   `/say hello`.
5. **Let him go:** put him on the floor, keep a finger near the **Space bar** (emergency stop), and type
   `/resume`.
6. **Walk away safely:** type `/pause` first, or `/quit` to shut him down. To power the Pi itself off, use
   `/shutdown` then `/shutdown confirm` (or the dashboard button), and never just pull the plug. See
   [Powering off](21-powering-off.md). In tmux, `Ctrl-B` then `D`
   leaves Bob running while you disconnect.

## The three things to remember

1. **Space on an empty console line is the emergency stop.** It cuts the motors and pauses Bob.
   `/clear` releases it.
2. **`/pause` stops Bob thinking** (and spending money). `/resume` starts him again.
3. **Make settings changes on your Mac**, then copy the project over. A copy from the Mac replaces the
   Pi's `config.toml`.

## Words used in these manuals

| Word | Meaning |
|---|---|
| **Pi** | the Raspberry Pi 4B computer inside Bob |
| **Console** | the text screen where you watch and command Bob |
| **Tick** | one round of Claude thinking: look, decide, act, then a short pause |
| **Tool** | an action Claude can ask for, such as `drive` or `speak` |
| **E-stop** | the emergency stop: Space, `/estop`, the dashboard button or an optional physical button |
| **Override** | a setting you control that Claude can't get around (stop, pause, motion off, mute...) |
| **`config.toml`** | Bob's settings file |
| **`.env`** | the private file with Bob's API key and passwords |
| **GPIO** | the pins on the Pi that connect to motors and sensors. Numbers here are "BCM" numbers, not physical pin positions |
| **SSH** | a way to type commands on the Pi from your Mac |
| **tmux** | keeps Bob running after you disconnect from SSH |

## What has been tested, honestly

Bob's code was tested on a Mac with simulated hardware, and many parts were tested with real data
(real speech, real face pictures, real wake word models). Some parts have been confirmed on your Pi:
the DC motors, the speaker, Piper speech, the microphone and the wake word. Parts that have **not yet
been confirmed on real hardware** say so in their manual: the USB camera, the distance sensor,
follow-me, calibration, the phone dashboard, the radio to John and the music system. Treat those as
"should work, expect to adjust".
