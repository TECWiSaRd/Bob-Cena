# Manual 05: Driving and motors

This manual covers how Bob moves: driving him by hand, the limits that keep him safe, and tuning the motors
so he drives smoothly and straight. For wiring, see [Hardware and wiring](01-hardware-and-wiring.md).

---

## Quick start: a bench test

Prop Bob up so **the wheels are off the ground**, start him paused, and try:

```
/speed 0.4         keep it gentle
/fwd 1             both wheels forward for 1 second
/back 1            both backward
/left 0.5          spin left (wheels turn opposite ways)
/right 0.5         spin right
```

If a wheel goes the wrong way, flip that wheel's `left_invert` or `right_invert` in `config.toml`
(`true` ↔ `false`), copy it over and restart.

---

## How Bob drives

Bob has one motor per side, like a tank:

| Wheels | Bob does |
|---|---|
| both forward | drives straight |
| both backward | reverses |
| one forward, one backward | spins on the spot |
| one faster than the other | curves (an "arc") |

Every movement, whether from you or Claude, has three numbers behind it: left power, right power (each -1
to 1) and a time. The wheels **always stop when the time runs out**.

---

## Driving by hand

| Command | What it does |
|---|---|
| `/drive` | keyboard driving: W/A/S/D or arrows, Q/E to arc, Space to stop, X or Esc to leave. Pauses the AI. On the shared console it is for you only; `/drive all` for everyone |
| `/fwd [s]`, `/back [s]` | 60% power, 1 s unless you give a time |
| `/left [s]`, `/right [s]` | spin at 60%, 0.5 s unless you give a time |
| `/move L R S` | exact powers, for example `/move 0.3 0.6 1.5` curves left for 1.5 s |

In `/drive` mode, holding a key keeps the wheels going (your keyboard's key-repeat keeps renewing a 0.6 s
move). Let go and they stop within about half a second. The phone dashboard has the same hold-to-drive
arrows: see [manual 07](07-camera-stream-and-dashboard.md).

## How Claude drives

Claude's `drive` tool takes a direction (`forward`, `backward`, `arc_left`, `arc_right`, `spin_left`,
`spin_right`), a speed from 0.1 to 1.0 and a time. His `set_wheels` tool sets each wheel directly. He's told
to move in short bursts and look again in between. You can stop him driving at any time with `/motion off`:
he still sees and talks. To get his turns right, run [calibration](06-calibration.md); his measured turn
rates are then shown to him every tick.

---

## The safety limits (Claude can't get around these)

| Limit | What it does | Change it with |
|---|---|---|
| **Speed cap** | every command is scaled down by it: at 0.8, "full speed" is 80% power | `/speed 0.5` live, or `max_speed` |
| **Longest move** | no single move can last longer than 3 s | `max_move_seconds` |
| **Watchdog** | checks 50 times a second and stops the wheels the moment a move's time runs out, even if the program hangs | always on |
| **Emergency stop** | cuts the wheels, switches off the motor driver (STBY), and blocks all motion until `/clear` | Space, `/estop`, dashboard, physical button |
| **Obstacle reflex** | with the distance sensor fitted, forward moves stop inside 15 cm | [manual 09](09-distance-sensor.md) |
| **Shutdown** | `/quit`, a crash or a service stop all stop the wheels and switch off the driver | always on |

Manual commands obey the speed cap, the emergency stop and the obstacle reflex too. Only `/motion off`
affects Claude alone.

---

## Tuning

### Wheel direction: `left_invert`, `right_invert`

Motors are mirror images on each side, so one normally runs backwards for "forward". The default is
`right_invert = true`. If `/fwd 1` turns a wheel backwards, flip that wheel's setting.

### Lowest working power: `/minduty`

DC motors don't move at very low power: they just hum. Bob maps every non-zero speed onto a range that
starts at `dc_min_duty` (default 0.25), so even a gentle command gets enough power to turn.

1. With the wheels off the ground, try `/move 0.05 0.05 1`.
2. If either wheel only hums, `/minduty 0.30`, then try again.
3. Keep raising it in small steps until both wheels start reliably. TT motors typically need 0.30-0.45.

### Driving straight: `/trim`

No two motors are identical, so one wheel is usually a little faster. Trim scales one wheel's power:

| Command | Effect |
|---|---|
| `/trim left 0.05` | left wheel 5% faster |
| `/trim right -0.03` | right wheel 3% slower |
| `/trim` | shows the current values |
| `/trim reset` | back to zero |

To find the right value by hand: put Bob on the floor, `/speed 0.6`, `/fwd 3`, and watch which way he
drifts. Drifts **left** → the left wheel is slow → `/trim left 0.05`. Repeat until he goes straight. Or let
him measure it himself: `/calibrate straight go` ([manual 06](06-calibration.md)). Trim applies at every
speed, including slow ones.

### Where tuning is saved

`/trim` and `/minduty` take effect immediately and are saved on the Pi in `tuning.json`, which overrides
`config.toml` when Bob starts. Copying the project from your Mac never touches it. Delete `tuning.json` to
go back to the `config.toml` values.

### Stopping style: `dc_brake`

With `dc_brake = true` (the default), stopped motors actively resist turning, so Bob stops crisply and
doesn't roll. Set `false` to let the wheels coast instead.

---

## Servo mode (alternative)

With continuous-rotation servos instead of DC motors, set `type = "servo"` under `[drive]`. Differences:

- Speed comes from the length of a control pulse (1.0-2.0 ms by default, `min_pulse_ms` / `max_pulse_ms`).
- Trim shifts that pulse, which also fixes a servo that creeps when it should be still.
- Steady pulses need the hardware PWM line in `/boot/firmware/config.txt`
  ([manual 01](01-hardware-and-wiring.md)). Without it, servos jitter.
- `pwm = "auto"` picks hardware PWM, then pigpio, then software PWM.
- `/minduty` and `dc_*` settings don't apply.

## A physical stop button

Wire a button between GPIO26 (pin 37) and ground, and set `estop_button_pin = 26`. Pressing it does the
same as Space. See [Safety](16-safety.md).

---

## Settings

All under `[drive]` in `config.toml`. Details: [settings reference](15-settings-reference.md).

| Setting | Default | In short |
|---|---|---|
| `type` | `"dc"` | `"dc"` or `"servo"` |
| `max_speed` | 0.8 | speed cap (0-1) |
| `max_move_seconds` | 3.0 | longest single move |
| `left_invert` / `right_invert` | false / true | wheel direction |
| `left_trim` / `right_trim` | 0.0 | drift correction |
| `dc_min_duty` | 0.25 | lowest working power |
| `dc_brake` | true | brake (true) or coast (false) |
| `dc_pwm_hz` | 20000 | motor switching speed (above hearing) |
| `dc_left_pwm`, `dc_left_in1`, ... `dc_standby` | 12, 5, 6, 13, 16, 20, 21 | motor driver pins |
| `estop_button_pin` | -1 | physical stop button pin; -1 = none |

## Troubleshooting

| Problem | Likely cause | Fix |
|---|---|---|
| Nothing moves, `SIM` on the status bar | the motor driver didn't start | read the `DRIVE UNAVAILABLE` line in the log |
| `E-stop active - /clear first` | the emergency stop is on | `/clear` |
| Claude says `BLOCKED ... disabled movement` | `/motion off` | `/motion on` |
| A wheel spins the wrong way | mirrored motor | flip its `_invert` setting |
| A wheel hums without moving | power too low | raise `/minduty` |
| Bob drifts | motors differ | `/trim` or `/calibrate straight go` |
| Jerky turns | very short moves at minimum power | normal for small corrections; try a lower `/speed` |
| Bob tips when a wheel jams | high, narrow body | lower the battery, add a rear skid, lower `max_speed` |
| Servos twitch instead of spinning | standard 180° servos | use continuous-rotation servos |
| Servos jitter | no hardware PWM | add the overlay line and reboot |
