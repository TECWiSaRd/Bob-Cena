# Manual 03: The console

The console is Bob's control room: a text screen on the Pi, which you open over SSH. It shows everything
Bob thinks and does as it happens, and it's where you type commands. This manual explains the screen,
the keys, and every command.

To open it, see [Installing and updating](02-installing-and-updating.md), Part 4. Short version:
`tmux attach -t bob` if Bob is already running, or `cd ~/bob && .venv/bin/python bob.py --paused`.

---

## The screen

```
 BOB  AUTO | thinking | motion on | camera on | mic hands-free (listening) | audio on | cap 0.80 | tick 12 | $0.412 | claude-opus-5-5/low
14:03:11 INFO  BOB  I see a doorway ahead. Heading over carefully.
14:03:12 INFO  MOVE L=+0.40 R=+0.40 for 1.0s
14:03:15 INFO  SAY  Oh hello! I'm Bob.
14:03:20 INFO  HEARD what's your name?
 SPACE (empty line)=E-STOP  TAB=talk  /help  PgUp/PgDn scroll --------------------------------
> _
```

1. **The status bar** (top line, white on black). It turns **red** during an emergency stop.
2. **The log** (the middle): everything that happens, newest at the bottom.
3. **The hint line**: reminders of the most important keys.
4. **The input line** (`>`): where you type.

### The status bar, piece by piece

| Shows | Meaning |
|---|---|
| `AUTO` / `PAUSED` / `E-STOP` / `MANUAL DRIVE` | what mode Bob is in. AUTO means Claude is running him |
| `thinking` / `idle` | whether a Claude request is in progress |
| `motion on` / `OFF` | whether Claude is allowed to drive (`/motion`) |
| `camera on` / `OFF` | the camera switch (`/camera`) |
| `mic ...` | microphone state: `off`, `hands-free (listening)`, `PTT (ready)`, `(transcribing)` and so on |
| `radio ...` | link to John (only when the radio is enabled) |
| `FOLLOWING`, `CALIBRATING`, `MUSIC` | shown while those are happening |
| `dist 42cm` | distance sensor reading (only when the sensor is enabled) |
| `audio on` / `MUTED` | the speaker switch (`/mute`) |
| `cap 0.80` | the speed cap: the fraction of full motor power anything may use |
| `tick 12` | how many thinking rounds Claude has done |
| `$0.412` | an estimate of what this session has cost in Claude API fees |
| `claude-opus-5-5/low` | the Claude model and effort level in use |
| `SIM` | hardware is being simulated (started with `--sim`, or the motors weren't found) |

### Log colours

| Colour | Lines |
|---|---|
| **Cyan** | Bob's thoughts (`BOB`), his speech (`SAY`) and sound effects (`SOUND`) |
| **Magenta** | what you typed (`YOU`) or said into the mic (`HEARD`) |
| **Green** | movements (`MOVE`), notes he saves (`NOTE`), radio messages (`RADIO`) |
| **Yellow** | warnings |
| **Red** | errors |

The full log is also saved on the Pi in `logs/bob.log`. Watch it from another window with
`tail -f ~/bob/logs/bob.log`.

---

## Keys

| Key | What it does |
|---|---|
| **Space** (on an empty line) | **EMERGENCY STOP** |
| **Tab** (on an empty line) | push-to-talk: start recording, press again to send |
| Enter | run what you typed |
| ↑ / ↓ | scroll through commands you've typed before |
| Page Up / Page Down | scroll the log (it shows `[scrolled N]` while you're back in the history) |
| Esc or Ctrl-U | clear the input line |
| Ctrl-C | quit Bob (same as `/quit`) |

**In manual drive mode** (`/drive`), the keys change:

| Key | Drives |
|---|---|
| W or ↑ | forward |
| S or ↓ | backward |
| A or ← | spin left |
| D or → | spin right |
| Q / E | arc left / arc right |
| Space | stop |
| X or Esc | leave drive mode |

Hold a key to keep moving. Each press drives for 0.6 s, and your keyboard's key-repeat keeps extending
it, so the wheels stop shortly after you let go.

---

## Talking to Bob

- **Type anything without a `/`** and press Enter: it's a message to Bob, and he answers out loud. If
  he's running, he answers at his next thinking round; if he's paused, it waits.
- **`/ask <message>`** (or `/tell`) sends a message and makes him answer **right away**, even while
  paused.

---

## Every command

Commands start with `/`. Type `/help` in the console for a short list.

### Stopping and pausing

| Command | What it does |
|---|---|
| `/estop` (or Space, or `/stop`) | **Emergency stop**: cuts the motors, switches off the motor driver, pauses the AI, stops following. Everything that moves is blocked until `/clear` |
| `/clear` | releases the emergency stop. The AI stays paused until you `/resume` |
| `/pause` (or `/hush`) | stops Bob thinking immediately, cancelling a request in progress. Also stops the wheels and any follow |
| `/resume` (or `/go`) | starts Bob thinking on his own again |
| `/think on` / `/think off` | the same as `/resume` / `/pause` |
| `/step` | one thinking round while paused. Handy for testing |
| `/quit` (or `/exit`) | shuts Bob down cleanly |

### Driving by hand

These work even while Bob is paused, and respect the speed cap and the emergency stop.

| Command | What it does |
|---|---|
| `/drive` | manual drive mode with the keyboard (pauses the AI). See "Keys" above |
| `/fwd [seconds]` | forward at 60% for 1 s (or the time you give) |
| `/back [seconds]` | backward at 60% for 1 s |
| `/left [seconds]` | spin left at 60% for 0.5 s |
| `/right [seconds]` | spin right at 60% for 0.5 s |
| `/move L R SECONDS` | each wheel's power from -1 (full reverse) to 1 (full forward), for example `/move 0.5 -0.5 1` |
| `/speed 0.4` | sets the speed cap for everything, you and Claude (0 to 1) |
| `/trim left 0.05` | makes one wheel faster (+) or slower (-) to fix drift. `/trim` shows, `/trim reset` clears |
| `/minduty 0.35` | the lowest motor power that actually turns the wheels |
| `/motion off` / `/motion on` | forbids or allows **Claude** driving (he still sees and talks). Your own manual driving still works |

Details: [Driving and motors](05-driving-and-motors.md).

### Bob's brain

| Command | What it does |
|---|---|
| `/model opus` / `sonnet` / `haiku` | switches the Claude model straight away. `/model` alone shows the current one. Haiku costs about 1/40th of Opus |
| `/effort low` (or `medium`, `high`, `xhigh`, `max`) | how hard Claude thinks each round: lower is quicker and cheaper |
| `/goal <text>` | gives Bob a new mission. `/goal` alone shows the current one |

Details: [The brain](04-brain-and-claude.md).

### Seeing

| Command | What it does |
|---|---|
| `/camera off` / `/camera on` (or `/cam`) | switches the camera off completely: nothing reaches Claude, the stream or `/snap` |
| `/snap` | saves a photo to `captures/` on the Pi |
| `/follow [seconds]` | follows the nearest face (default 30 s) |
| `/follow off` | stops following |
| `/range` (or `/sensor`) | distance sensor reading. Also `/range stop 25` (stop distance in cm) and `/range off`/`on` (the reflex) |
| `/calibrate turn` / `straight` / `show` / `cancel` | Bob measures his own turning and drift. Add `go` to actually start |

Details: [Camera](07-camera-stream-and-dashboard.md), [Follow me](08-follow-me.md),
[Distance sensor](09-distance-sensor.md), [Calibration](06-calibration.md).

### Speaking and listening

| Command | What it does |
|---|---|
| `/say <text>` | Bob says it out loud |
| `/sound <name>` | plays a sound: `beep`, `chirp`, `happy`, `sad`, `question`, `alert`, `startup` |
| `/mute` / `/unmute` | silences all of Bob's audio (speech and sounds) |
| `/listen on` / `/listen off` (or `/mic`) | starts or stops the microphone |
| `/listen` | microphone status and the live loudness level |
| `/listen mode ptt` / `hands-free` | push-to-talk or always listening |
| `/listen threshold 0.03` | how loud counts as speech |
| `/listen wake ...` | wake word settings: `off`, `oww`, `text`, `sleep`, `threshold 0.6`, `window 20` |
| `/talk` (or Tab) | push-to-talk: start recording, then again to send |

Details: [Voice and sounds](10-voice-and-sounds.md), [Microphone](11-microphone-and-wake-word.md).

### Memory

| Command | What it does |
|---|---|
| `/notes` | shows Bob's long-term notes |
| `/forget` | wipes all his notes |
| `/people` | shows everyone Bob knows |
| `/people forget Sam` | forgets one person. `/people clear` forgets everyone |

Details: [Memory and people](14-memory-and-people.md).

### Music and radio

| Command | What it does |
|---|---|
| `/music` | what's playing. Also `play`, `pause`, `next`, `prev`, `vol 40`, `vol up`/`down`, `pair`, `devices`, `forget MAC`, `ai on`/`off` |
| `/radio` | the link to John. Also `log 20`, `say <text>`, `on`/`off`, `ai on`/`off` |

Details: [Sound system](12-sound-system.md), [Radio to John](13-radio-to-john.md).

---

## How overrides work

Every action Claude asks for is checked against your switches **at the moment it would happen**, not when
he decided on it. So if Claude has already decided to drive forward and you press Space, the drive is
refused. Refused actions go back to Claude as a message starting with `BLOCKED`, and he's told not to
argue or try to get around it.

## Running without the screen

`.venv/bin/python bob.py --headless` prints the log as plain text and reads commands one line at a time.
It's useful for scripts and testing. All the same commands work, but there are no keys (type `/estop`
for an emergency stop).

## Troubleshooting

| Problem | Fix |
|---|---|
| The screen looks garbled | make the Terminal window bigger (at least 100 columns), or press any key to redraw |
| Space doesn't stop him | the input line must be empty. Press Esc first, then Space. Or type `/estop` |
| Arrow keys type letters | your terminal sends unusual codes: use W/A/S/D in drive mode |
| `unknown command` | check the spelling with `/help` |
| Commands do nothing over a slow connection | the console still works; the delay is the network. Use the dashboard on a phone as a backup |
