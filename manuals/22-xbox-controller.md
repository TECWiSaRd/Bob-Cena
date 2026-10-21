# Manual 22: Xbox controller

Drive Bob with an Xbox controller (Xbox One, Series X|S, 360, or most similar pads). It works by USB or Bluetooth,
and nothing extra needs installing: Bob reads the controller the way Linux presents it (`/dev/input/js0`).

**Status:** tested with a simulated controller (including unplugging it mid-drive). I haven't tried a real one
yet, so the button numbers below might differ for your model. [Troubleshooting](#troubleshooting) shows how to
check and change them.

---

## Turn it on

1. In `config.local.toml` (see [manual 02](02-installing-and-updating.md)):
   ```toml
   [gamepad]
   enabled = true
   ```
2. Connect the controller, either:
   - **USB:** plug it in. Done.
   - **Bluetooth:** on the Pi, run `bluetoothctl`, then `scan on`, hold the controller's pairing button (the small
     button on top) until the Xbox light flashes fast, and when it appears: `pair AA:BB:CC:DD:EE:FF`,
     `trust AA:BB:CC:DD:EE:FF`, `connect AA:BB:CC:DD:EE:FF`.
3. Restart Bob. The log says `Gamepad connected: Xbox Wireless Controller`. If you connect it later, Bob notices
   within two seconds.

`/check` has a `controller` line: green when one is connected, a warning when none is found.

## The buttons

| Control | Does |
|---|---|
| **Start** (Menu) | manual driving on or off. Turning it on pauses the AI, like `/drive` |
| **Left stick** | drive: up and down go forward and back, left and right turn. Push diagonally to arc |
| **LB** (hold) | slow mode (40% speed) |
| **B** | **emergency stop**. Always works, even when you aren't driving |
| **Back** (View), hold 1.5 s | release the emergency stop (same as `/clear`) |
| **Y** | hand control back to the AI (same as `/resume`) |
| **A** | push-to-talk |

Pressing **Start** again leaves manual driving. The AI stays paused until you press **Y** or type `/resume`.

## How it stays safe

- The speed cap (`/speed`) still applies to everything the stick does.
- The stick only moves Bob while manual driving is on. Nothing happens if you brush it while the AI is running.
- Each stick reading moves the wheels for under half a second, so if the signal is lost they stop on their own.
- **If the controller disconnects or its battery dies, the wheels stop at once** and the log says so.
- When a controller connects, whatever buttons happen to be held are ignored, so connecting never triggers anything.
- The emergency stop blocks the stick until you release it with Back (held) or `/clear`.
- Claude cannot press any of these buttons.

## Settings (`[gamepad]`)

| Setting | Default | What it does |
|---|---|---|
| `enabled` | false | turn controller support on |
| `device` | `"auto"` | `"auto"` uses the first controller found, or give a path such as `"/dev/input/js1"` |
| `deadzone` | 0.15 | stick wobble below this is ignored |
| `slow_factor` | 0.4 | speed fraction while LB is held |
| `axis_turn`, `axis_throttle` | 0, 1 | which stick directions steer and drive |
| `btn_talk`, `btn_estop`, `btn_resume`, `btn_slow`, `btn_back`, `btn_drive` | 0, 1, 3, 4, 6, 7 | which button number does what (A, B, Y, LB, Back, Start) |

## Troubleshooting

| Problem | Fix |
|---|---|
| `Gamepad: waiting for a controller` stays | no `/dev/input/js0`. Run `ls /dev/input/js*` and `dmesg \| tail`. Over Bluetooth, check `bluetoothctl info AA:BB:...` says `Connected: yes` |
| Bluetooth connects, then drops or shows no `js0` | some Xbox Series controllers need a newer kernel or the `xpadneo` driver. Update the Pi (`sudo apt full-upgrade`) and reboot, or use USB |
| Wrong buttons do things | install `joystick` (`sudo apt install joystick`), run `jstest /dev/input/js0`, press each button to see its number, and change the `btn_` and `axis_` settings |
| Steering is reversed | swap which direction you push, or change `axis_turn`. If it is only inverted, tell me and I'll add an invert setting |
| Bob doesn't move with the stick | manual driving is off: press Start. Also check the e-stop (status bar) and the speed cap |
| Nothing happens at all | `/check` shows the `controller` line; `enabled = true` must be under `[gamepad]` and Bob restarted |
