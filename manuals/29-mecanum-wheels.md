# Manual 29: Mecanum wheels (sliding sideways)

Normal Bob drives like a tank: the wheels on one side always move together. **Mecanum wheels** have angled rollers, and a tank-style
command makes them slip and drift when he turns. In mecanum mode each of the four wheels gets its own speed, so Bob turns cleanly on the
spot and can also **slide left and right** without turning.

This is off by default. Nothing changes for a normal two- or four-wheel robot. It has only been tested with pretend motors, not on a real
robot, so go slowly the first time.

## What you need

- Four DC motors with four mecanum wheels, two TB6612FNG boards, `type = "dc"`.
- **Every wheel on its own pins.** The easy "rear board in parallel" wiring from manual 01 can't do this, because a parallel board copies
  the front wheel. Give each rear wheel its three pins (`dc_rear_left_*` and `dc_rear_right_*`). Bob refuses to start the wheels (and simulates)
  if one is missing, rather than drive wrongly.
- The wheels mounted the right way round: the rollers touching the floor should make an **X** seen from above, with left-handed and right-handed wheels in the right corners.

```toml
[drive]
drive_style = "mecanum"
dc_wheels = 4
dc_rear_left_pwm = 18
dc_rear_left_in1 = 27
dc_rear_left_in2 = 22
dc_rear_right_pwm = 19
dc_rear_right_in1 = 25
dc_rear_right_in2 = 4
```

Use pins that are free on your robot (not the distance sensor's, for example).

## Setting it up, step by step

1. **Wheels off the ground**, battery connected, `/speed` low (for example `/speed 0.3`).
2. `/fwd 1`: all four wheels turn forwards. A wheel that goes backwards: swap its motor wires, or set `left_invert` / `right_invert`
   (front and rear on that side) or `rear_left_invert` / `rear_right_invert` (the rear wheel only).
3. `/left` and `/right`: a spin, so the left wheels go one way and the right wheels the other.
4. `/strafe right 1`: seen from above, the **front-left and rear-right** wheels turn forwards and the **front-right and rear-left** turn
   backwards. On the floor the robot slides to its right. If it slides the wrong way, or turns instead of sliding, the wheels are mounted
   the wrong way round (the roller pattern): swap them until the sideways slide is right.
5. On the floor, at low speed, in a clear space. Then run `/calibrate` again with the mecanum wheels on, on the floor he'll use: the old turn numbers were measured for a different drive.

## Commands

| Command | What it does |
|---|---|
| `/strafe left [secs]`, `/strafe right [secs]` | slide sideways (default 0.8 s) |
| `/move L R SECS [S]` | raw wheel speeds; the optional fourth number is sideways, -1 (left) to 1 (right) |

If the robot is not in mecanum mode, `/strafe` says so and does nothing. The dashboard, app joystick, Xbox controller and micro:bit do not
slide yet; they drive and turn as before.

## Claude and the safety rules

When mecanum is on, Claude's `drive` tool also offers `strafe_left` and `strafe_right`. He is told that his distance sensor only looks
forward, so he should look before he slides. On a tank robot those choices don't exist, and the drive code refuses them anyway.

Every safety limit applies to all four wheels exactly as before: the `/speed` cap, emergency stop (it also cuts the standby pin of both
boards), `/pause`, `/motion off`, sleep mode, the move time limit and the watchdog that stops the wheels when a move runs out. A command that
needs more than full speed on one wheel is scaled down on all four together, so the direction stays right.

**The distance sensor can't see sideways.** It only stops forward moves, so a pure slide is not stopped by it. Keep sideways space clear.

## Settings

| Setting | Default | What it does |
|---|---|---|
| `drive_style` | tank | `tank` or `mecanum` |
| `dc_wheels` | 2 | must be `4` for mecanum |
| `dc_rear_left_pwm`, `_in1`, `_in2`, `dc_rear_right_pwm`, `_in1`, `_in2` | -1 | all six needed for mecanum |
| `left_invert`, `right_invert` | | flip a side (both wheels on it) |
| `rear_left_invert`, `rear_right_invert` | false | flip one rear wheel |

## If it doesn't drive right

| What happens | Likely cause |
|---|---|
| Bob says "DRIVE UNAVAILABLE ... simulating" at start | a rear wheel's pins are missing, or `dc_wheels` isn't 4 |
| Forward is fine but sliding turns him instead | the wheels are in the wrong corners (roller pattern); swap them |
| Sliding goes the wrong way | swap left and right wheels, or ask for the opposite direction |
| One wheel turns backwards in `/fwd` | flip that wheel's invert setting or swap its wires |
| Slides drift forwards or back | a wheel is slower than the others: trim with `/trim` |
