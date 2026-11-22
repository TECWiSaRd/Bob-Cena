# Manual 31: Controlling Bob over Bluetooth

For when there is no good Wi-Fi: an event hall, a field, a hotspot that dropped. The Bob app (or the check tool below) talks to Bob directly over Bluetooth LE, a few metres
apart, with no network at all. It can **drive, stop, show his status, run the same short list of commands the app uses over Wi-Fi, and press the emergency stop**. It cannot
send video (Bluetooth is far too slow for a picture), so on a Bluetooth link you steer by looking at the robot.

> **Status: stage 1.** Bob's side is built and tested with a pretend Bluetooth radio. It has **not yet been tried on a real Pi**, and **the app has no Bluetooth button yet**: until it does, use
> the check tool below to test it, and for an event plan on the Xbox controller or a phone hotspot as well (manual 22).

## What it needs

- **On Bob (a Pi with Bluetooth, such as a Pi 3, 4 or 5):** the Bluetooth service `bluetoothd` running (it is by default), and the `bless` package: `./install.sh` adds it, or
  `.venv/bin/pip install bless`. Then in `config.local.toml`:
  ```toml
  [ble]
  enabled = true
  ```
  and restart Bob. `/ble` says whether it is running. The log says `Bluetooth control is on` or why not.
- **The app (or tool) paired once over Wi-Fi first,** at home. While paired, it asks Bob for its own **Bluetooth key**, a long secret kept with that device in `devices.json`. Without that key nobody can
  drive Bob over Bluetooth, even standing next to him. Unpairing the device (`/devices remove NAME`) takes the key away at once.

## Trying it, with the check tool (from your Mac, near Bob)

```bash
pip install bleak
python3 tools/ble_check.py --host 192.168.1.50 --code ABCD1234EFGH        # first time: /pair on Bob gives the code
python3 tools/ble_check.py --device a1a0a419 --key <the key it printed>   # later runs
python3 tools/ble_check.py --device ... --key ... --drive                 # also one gentle forward pulse and a stop (wheels lifted!)
```
It finds Bob's Bluetooth service, says hello, asks for his status and prints what he answers. **Please try this at home before you rely on it anywhere else**, and tell whoever is
looking after the code what it prints if it doesn't work. Remove the test device afterwards with `/devices remove ble-check`.

## How it stays safe

- **Every command is signed** with the device's key and a fresh number Bob makes up for each hello, and counts up, so a message can't be forged, changed, or replayed later.
- **A drive pulse lasts 0.4 seconds.** The app repeats it about four times a second while you hold the stick, so if the link drops or the phone goes out of range, he stops by himself.
- The **speed cap**, `/pause`, `/motion off`, sleep mode and the emergency stop work exactly as for any other driving. Commands are limited to the app's own list, so there is no way to
  shut down, update, pair devices or quit.
- **Wrong signatures** are counted: after eight in a minute he ignores everything but the emergency stop for a minute.
- **The emergency stop** can be sent by anyone in Bluetooth range without a key, because all it ever does is stop him. If you would rather it needed a key too, set `open_estop = false`.
- Claude has no tool to use this. Bluetooth LE messages are signed but **not encrypted**: someone nearby with a radio sniffer could read the commands (not forge them).

## Settings (`[ble]`)

| Setting | Meaning | Default |
|---|---|---|
| `enabled` | Bluetooth control | `false` |
| `open_estop` | anyone nearby may send the emergency stop without a key | `true` |
| `max_per_second` | the most messages per second he will act on | `20` |

## If it doesn't work

| What you see | Likely cause |
|---|---|
| `/ble` says `NOT running (... bless ...)` | `pip install bless` in Bob's `.venv`, then restart him |
| `Could not locate bluetooth adapter` in the log | no Bluetooth adapter, or `bluetoothd` isn't running: `sudo systemctl start bluetooth` |
| the tool can't find Bob | `[ble] enabled` is off, Bob wasn't restarted, or you are too far away (try within 2 metres) |
| `ERR unknown device` | this device never asked for a Bluetooth key: pair it over Wi-Fi first (the tool does it with `--host` and `--code`) |
| `ERR auth` or `ERR locked` | the wrong key, or too many wrong tries: wait a minute |
| `ERR session` | say hello again (the app does this by itself) |

The message format is in `blecodec.py`; `tests/test_ble.py` holds numbers the app's own tests must match.
