# Manual 27: Driving Bob with a micro:bit

A BBC micro:bit can be a small remote control for Bob. Tilt it to steer, press its buttons to start and stop. It connects three ways:

- **USB cable** to the Pi (version 1 or 2)
- **Radio:** a second micro:bit plugged into the Pi passes messages along (version 1 or 2)
- **Bluetooth:** a version 2 micro:bit talks straight to the Pi's own Bluetooth, so no second micro:bit is needed

> **Not tested on a real Pi yet.** The Pi side (USB, and Bluetooth with a pretend Bluetooth library) is tested; the micro:bit programs have
> not been flashed to real hardware, and the pairing steps are from MakeCode's documentation, not tried. Try it with the wheels off the ground first.

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

## Over Bluetooth (micro:bit V2)

1. Install the support once: `./install.sh` (it adds `bleak`). Make sure the Pi's Bluetooth is on: `bluetoothctl power on`.
2. On <https://makecode.microbit.org> make a new project, open the **JavaScript** tab and paste `microbit/bob_remote_ble.ts`. Add the
   **bluetooth** extension (gear icon, Extensions) and, under Project Settings, choose **Just Works Pairing**. Download it to the micro:bit.
3. **Pair it with the Pi** (this stops anyone else connecting): on the micro:bit hold **A and B**, tap the back **reset** button, and keep
   holding A and B until the pairing pattern shows. Then on the Pi:
   ```
   bluetoothctl
   scan on                     # wait for "BBC micro:bit [xxxxx]", note its address and the five letters
   pair AA:BB:CC:DD:EE:FF
   trust AA:BB:CC:DD:EE:FF
   ```
4. In `config.local.toml`:
   ```toml
   [microbit]
   enabled = true
   transport = "ble"
   ble_name = "xxxxx"          # the five letters from its name; leave empty and Bob would take any micro:bit in range
   key = "pick-a-short-word"
   ```
   Put the same word in `KEY` at the top of the MakeCode program. Restart Bob.

Only one thing can be connected to the micro:bit at a time, so while the Pi has it, a phone or a stranger can't. If Bob can't find it,
check it isn't still connected to a phone, and that it shows the little diamond (waiting). The Bluetooth radio is shared with the speaker
and the Xbox controller; if the music stutters while the micro:bit is connected, use the USB or radio way instead.

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
| `transport` | `"usb"` (cable or radio bridge) or `"ble"` (Bluetooth) | `"usb"` |
| `device` | USB only: `"auto"` finds a micro:bit by its USB name, or a path like `"/dev/ttyACM0"` | `"auto"` |
| `ble_name` | Bluetooth only: the five letters in its name (`BBC micro:bit [tupaz]`) | `""` |
| `ble_address` | Bluetooth only: or its address (wins over the name) | `""` |
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
| Bluetooth: "no micro:bit found" in the log | it must be switched on, near the Pi, not connected to a phone, and `ble_name` must be its five letters |
| Radio does nothing | `GROUP` must match; bridge plugged into the Pi; the handheld within a few metres |
