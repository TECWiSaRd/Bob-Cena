# Manual 17: Troubleshooting

Problems and fixes, grouped by area. Most of these came up while Bob was being built, so they're real.
Each part's own manual has more detail.

**First moves for almost any problem:**
0. **Type `/check`.** It tests the camera, motors, speaker, microphone, power supply, temperature, disk and
   Wi-Fi in one go, and names what's wrong.
1. **Read the log.** Scroll up in the console (Page Up), or `tail -50 ~/bob/logs/bob.log`. Bob explains most
   failures in plain words, in yellow (warnings) or red (errors).
2. **Check the status bar.** `E-STOP`, `PAUSED`, `motion OFF`, `camera OFF`, `audio MUTED` and `SIM` explain
   a lot of "why isn't he doing anything".
3. **Restart Bob** after changing settings or copying code: `/quit`, then start him again.

---

## Connecting to the Pi

| Problem | Cause | Fix |
|---|---|---|
| `Could not resolve hostname bob.local` | the name doesn't work on your network | use the IP (`hostname -I` on the Pi) or Tailscale (`ssh adam@bob`) |
| SSH times out but the Pi is on | the Pi's IP changed, or the Mac and Pi are on different networks | check `hostname -I` on the Pi; compare the first three numbers with your Mac's |
| SSH slow or dropping; ping times jump around | Wi-Fi power saving | `sudo iw dev wlan0 set power_save off`, made permanent in [manual 02](02-installing-and-updating.md) |
| `No route to host` | different network, or macOS blocking local network access | System Settings → Privacy & Security → Local Network: allow Terminal |
| `REMOTE HOST IDENTIFICATION HAS CHANGED` | the Pi was reinstalled, or the address now belongs to another device | `ssh-keygen -R <address>`, then connect again |
| `Permission denied` | wrong username or password | the username you set in Raspberry Pi Imager |

## Installing

| Problem | Fix |
|---|---|
| `./install.sh: Permission denied` | `chmod +x install.sh` |
| Lines starting `!!` in the output | each is an optional piece that didn't install; the line says what Bob does instead |
| The install was interrupted (power cut) | `sudo dpkg --configure -a`, `sudo apt-get -f install -y`, `rm -rf .venv`, then `./install.sh` |
| `tmux: command not found` | `sudo apt-get install -y tmux` |
| `openwakeword 0.4.0` was installed | `.venv/bin/pip install --no-deps --upgrade 'openwakeword>=0.6'` |
| `No module named 'openwakeword'` when scoring | install it the same way as above |
| Bob won't start: `unknown setting [...]`, `unknown section [...]` or `isn't one of: ...` | a typo in `config.toml`: fix the setting it names |
| Bob won't start: `... should be int` (or bool, str) | a setting has the wrong kind of value: compare with [manual 15](15-settings-reference.md) |

## Motors and driving

| Problem | Cause | Fix |
|---|---|---|
| Nothing moves, log shows `TB6612FNG ready` | no shared ground, STBY not wired, or no motor battery | check the wiring checklist in [manual 01](01-hardware-and-wiring.md) |
| Nothing moves, `SIM` on the status bar | the motor driver didn't start | read the `DRIVE UNAVAILABLE` line in the log |
| `E-stop active - /clear first` | the emergency stop is on | `/clear` |
| Claude is `BLOCKED` from moving | `/motion off` | `/motion on` |
| One wheel spins backwards | mirrored motor | flip `left_invert` / `right_invert` |
| A wheel hums but doesn't turn | too little power at low speed | raise `/minduty` (try 0.35) |
| Bob drifts left or right | the motors differ | `/trim`, or `/calibrate straight go` |
| The Pi reboots when motors start | motors powered from the Pi | separate motor battery, shared ground |
| Servos twitch instead of spinning | standard 180° servos (such as SG90) | use continuous-rotation servos, or the DC motors |
| Servos jitter | no hardware PWM | add the `pwm-2chan` line to `/boot/firmware/config.txt`, reboot ([manual 01](01-hardware-and-wiring.md)) |
| `Unit pigpiod.service could not be found` | newer Pi OS doesn't include pigpio | not needed: Bob uses hardware PWM instead |
| A power module's LED stays off | no input power, a charge-only cable, or a switch | try another cable and charger; check for a power switch |

## Camera

| Problem | Fix |
|---|---|
| Log: `No working camera`, Bob says he's blind | `lsusb` (USB camera listed?), `v4l2-ctl --list-devices`, or `rpicam-hello --list-cameras` |
| `can't open /dev/video0` | try `[camera] device = 1`, or the number `v4l2-ctl` shows |
| Picture upside down | `rotate_180 = true` |
| Bob says he can't see, camera works | `/camera on` (it may be switched off) |
| Stream page asks for a password, or says `unauthorized` | add `?token=<BOB_STREAM_TOKEN>` to the address |
| Dashboard "is off" | `BOB_STREAM_TOKEN` missing or under 8 characters |

## Voice and sound

| Problem | Fix |
|---|---|
| No sound at all | `speaker-test -t wav -c 2 -l 1`. Silent too? Pick the output: `sudo raspi-config` → System Options → Audio |
| `speaker-test` works but Bob is silent | `/unmute` (status bar shows `audio MUTED`?) |
| Robotic voice | Piper isn't being used: read the log; `.venv/bin/pip install piper-tts` |
| Speech takes about 5 s to start | that was fixed (the voice now stays loaded). Still slow? Use a `-low` voice ([manual 10](10-voice-and-sounds.md)) |
| Quiet | `alsamixer`, or `wpctl set-volume @DEFAULT_AUDIO_SINK@ 80%` |

## Microphone and wake word

| Problem | Fix |
|---|---|
| `audio open error: No such file or directory` | wrong mic name: `arecord -l`, then set `[mic] device` (yours: `plughw:CARD=Device,DEV=0`) |
| `Giving up on the microphone` | fix the cause above, then `/listen on` |
| Recording is silent or faint | `alsamixer -c 4`, F4, unmute (`M`), level 70-80% |
| `faster-whisper isn't installed` | `.venv/bin/pip install faster-whisper` |
| `openWakeWord is missing or too old` | `.venv/bin/pip install --no-deps --upgrade 'openwakeword>=0.6'` |
| He only reacts to the first "Hey Bob" | the 20 s window is still open; `/listen wake sleep` between tests |
| "Hey Rob" wakes him | a weakness of the downloaded model; see [manual 11](11-microphone-and-wake-word.md) |
| He doesn't hear you while driving or playing music | deliberate: the mic is deaf then. Use push-to-talk (Tab) |
| `HEARD` shows words nobody said | background noise: raise `/listen threshold` |

### Training a wake word in Colab

| Error | Fix |
|---|---|
| `No matching distribution found for piper-phonemize-cross` | Colab's Python is too new for the notebook: see section 2c of [TRAINING_HEY_BOB.md](../TRAINING_HEY_BOB.md) |
| `No module named 'piper_phonemize'` | in cell 1, change `piper-phonemize-cross` to `piper-phonemize-fix` |
| `train.py ... No module named 'openwakeword'` | install it without dependencies and set `PYTHONPATH` (TRAINING_HEY_BOB.md, 2c) |
| `positive_features_train.npy` not found, or `best_models is not defined` | an earlier step failed: scroll up to the first red error |

## Claude (the brain)

| Problem | Fix |
|---|---|
| `Claude API key rejected` | check `ANTHROPIC_API_KEY` in `.env`, restart |
| `Can't reach the Claude API` | no internet: check Wi-Fi; Bob retries by himself |
| `Rate limited` | too many requests: Bob waits and retries; raise `tick_seconds` |
| He does nothing, status `PAUSED` | `/resume` |
| He's oddly cautious or stuck on an idea | an old note: `/notes`, then `/forget` |
| Costs are high | `/pause` when not watching, `/model haiku` for testing, raise `tick_seconds` |

## Following, sensor and calibration

| Problem | Fix |
|---|---|
| `can't follow: no camera picture` | camera off or missing |
| He swings left and right while following | lower `[follow] turn_gain` |
| Distance sensor always reads "clear" | wiring, especially ECHO through the divider and the shared ground |
| Calibration: `pause Bob first` | `/pause` |
| Calibration: `not enough detail` | point him at furniture, not a blank wall |

## Music and radio

| Problem | Fix |
|---|---|
| `/music` says music is off | `[music] enabled = true`, after running `./install_music.sh` |
| `PipeWire tools not found` | run `./install_music.sh` |
| Phone can't find Bob | `/music pair` again; pairing only stays open for 2 minutes |
| Phone pairs but shows a phone icon, with no "Media audio" option | the Pi isn't offering the speaker profile: `bluetoothctl show \| grep -i uuid` has no `Audio Sink`. Re-run `./install_music.sh` (it turns off WirePlumber's desktop-login check), then `systemctl --user restart wireplumber`. Forget Bob on the phone and pair again |
| No AirPlay "Bob" | same Wi-Fi? `systemctl --user status shairport-sync` |
| Radio: `waiting for John` forever | John running, set to `connect`, pairing done? `bluetoothctl devices` |
| Radio: `failed authentication` | the two `BOB_RADIO_SECRET` values differ |

---

## Getting help

When asking for help, paste:
1. **The exact error**, especially the first red line, and a few lines before it.
2. **What you did** just before it happened.
3. **The status bar line.**
4. For hardware problems, **the relevant log lines from startup** (`head -40 ~/bob/logs/bob.log`).

Never paste your `.env` file, API key, `BOB_STREAM_TOKEN`, `BOB_RADIO_SECRET` or AirPlay password.
