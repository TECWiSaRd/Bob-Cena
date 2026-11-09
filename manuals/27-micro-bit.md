# Manual 27: Driving Bob with a micro:bit

A BBC micro:bit (version 1 or 2) can be a small remote control for Bob. Tilt it to steer, press its buttons to start and stop.
It works over a USB cable, or wirelessly with a second micro:bit plugged into the Pi.

> **Not tested on a real Pi yet.** The Pi side is tested with a pretend micro:bit; the micro:bit programs have not been flashed
> to real hardware. Try it with the wheels off the ground first.

## What the controls do

| On the micro:bit | What Bob does |
|---|---|
| **Hold A** and tilt | Drive. Tilt away from you = forward, sideways = turn. Let go of A and Bob stops. |
| **Tap B** | Manual driving on or off (turning it on pauses the AI, like the keyboard and the Xbox controller) |
| **A and B together** | **Emergency stop.** Always works. |
| **Touch the logo** (V2 only) | Push-to-talk |
| **Hold B for 3 seconds** | Release the emergency stop. Off unless you turn it on (see Safety). |

The micro:bit's screen shows what Bob is doing: a smile when idle, an arrow while driving by hand, a cross during an emergency stop.

## What you need

- one micro:bit (a second one if you want it wireless) and a USB cable per micro:bit that goes to the Pi
- the install script run once (`./install.sh`): it adds `pyserial` and lets your Pi account open USB serial ports. **Reboot, or log out and in, once** after the first run.

## Setting it up

1. Open <https://python.microbit.org> in a browser.
2. **Plugged in directly:** paste the contents of `microbit/bob_remote.py`, flash it, and plug that micro:bit into the Pi.
   **Wireless:** flash `microbit/bob_remote.py` onto the handheld one and `microbit/bob_bridge.py` onto the one that stays plugged into the Pi.
   Set `GROUP` to the same number (0 to 255) in both.
3. In `config.local.toml` on your Mac (then `./deploy.sh`):
   ```toml
   [microbit]
   enabled = true
   key = "pick-a-short-word"
   ```
   Put the same word in the `KEY = ""` line of `bob_remote.py` before you flash it.
4. Restart Bob. `/check` shows a **micro:bit** line: connected, or waiting for one.

## Safety

- **Everything else still applies:** the speed cap, the distance-sensor stop, `/pause`, `/motion off`, sleep mode and the emergency stop. Claude has no way to use the micro:bit.
- **A dead man's switch.** A tilt only moves Bob for a fraction of a second. If you let go of A, move out of radio range, or unplug it, Bob stops.
- **The radio is not secure.** Anyone nearby with a micro:bit on the same group number could send it messages. That is why:
  - the emergency stop needs no key (a stranger can only ever make Bob stop),
  - driving, talking and manual mode ignore messages without your `key`. The key is a casual lock, not strong security: pick one, and keep the micro:bit wired if you don't want to rely on it.
  - releasing the emergency stop from the micro:bit is **off**. Set `allow_clear = true` only if you want it. Otherwise use `/clear` from the console or the app.
- Set `drive = false` and the micro:bit can only press the emergency stop.

## Settings (`[microbit]`)

| Setting | Meaning | Default |
|---|---|---|
| `enabled` | turn the micro:bit on | `false` |
| `device` | `"auto"` finds a micro:bit by its USB name, or a path like `"/dev/ttyACM0"` | `"auto"` |
| `deadzone` | tilt smaller than this fraction is ignored | `0.2` |
| `speed` | full tilt = this fraction of the speed cap | `0.6` |
| `drive` | `false` = emergency stop only | `true` |
| `key` | short word the micro:bit also knows | `""` |
| `allow_clear` | holding B may release the emergency stop | `false` |

## If it doesn't work

| What you see | Try |
|---|---|
| `/check` says "no micro:bit found" | different USB cable (some only charge), then `ls /dev/serial/by-id/` on the Pi |
| "Permission denied" in the log | reboot once after `./install.sh` so the `dialout` group takes effect |
| Bob ignores tilts | tap B first (manual driving), check the keys match, hold A while tilting |
| Wireless does nothing | `GROUP` must match; bridge plugged into the Pi; the handheld within a few metres |
