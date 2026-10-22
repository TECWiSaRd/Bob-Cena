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

## The console screen

| Problem | Fix |
|---|---|
| Stray text (warnings, camera messages) appears on top of the console | Bob now sends everything that libraries and helper programs write to the terminal into `logs/stderr.log` while the console is up. Read it with `tail -50 ~/bob/logs/stderr.log` (it also holds a traceback if Bob crashed). If you still see stray text, press `Ctrl-L`-style redraw by resizing the window, and tell me what it said |
| Garbled in `bob-console` | make the terminal at least 100 columns wide |

## Camera

| Problem | Fix |
|---|---|
| Log: `No working camera`, Bob says he's blind | `lsusb` (USB camera listed?), `v4l2-ctl --list-devices`, or `rpicam-hello --list-cameras` |
| `can't open /dev/video0` | try `[camera] device = 1`, or the number `v4l2-ctl` shows |
| Picture upside down | `rotate_180 = true` |
| Log: `Camera is not responding` (then `Restarting Bob now`) | the camera driver hung. Under the service Bob restarts himself in a few seconds. If it repeats: check the camera ribbon is seated and away from the motor wires, the power supply, and `sudo dmesg \| grep -i unicam`; a reboot clears a wedged driver. Started by hand, he stays up: restart him yourself. Setting: `[camera] restart_after_s` |
| Bob says he can't see, camera works | `/camera on` (it may be switched off) |
| Stream page asks for a password, or says `unauthorized` | add `?token=<BOB_STREAM_TOKEN>` to the address |
| Dashboard "is off" | `BOB_STREAM_TOKEN` missing or under 8 characters |
| A friend's token says `unauthorized` | `/access` shows the Wi-Fi network Bob is on and which names work there. The network name in `.env` must match exactly (`WIFI[Kai's House]=KAI`). Restart Bob after editing `.env` |
| `too many wrong tries: wait a minute` | that device guessed wrong 8 times in a minute: wait a minute |

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

## Home Assistant

| Problem | Fix |
|---|---|
| `Home Assistant disabled: ...` at startup | the message says what's missing: usually `HA_TOKEN` in `.env`, or `rooms` |
| `can't reach Home Assistant` | check `url` (try the IP address) from the Pi: `curl http://<address>:8123` |
| `I don't know which room I'm in` | `/where <room>`, or fix the room sensor |
| He reads the tag from the next room through a door | stand him where he should NOT count it and look at `/tags`; then run `/tags min` at the farthest spot he SHOULD count it, or raise the number |
| `/locate` finds nothing | stand him where a tag is in view, check height and size with `/tags` (manual 19) |
| `/tags` shows nothing | see "Room tags" in [Home Assistant](19-home-assistant.md): height, size, glare, and `tag_min_px` |
| He won't turn lights on | quiet hours, the 30 s cooldown, or `/home ai off`: the message says which |

More in [Home Assistant](19-home-assistant.md).

## Shared console

| Problem | Fix |
|---|---|
| A friend gets `... isn't allowed` | `./install_remote.sh --add NAME` (or `--add NAME --view`) |
| `bob-console: command not found` | run `./install_remote.sh` on the Pi |
| `Bob isn't running, or the shared console is off` | start Bob; `enabled = true` under `[remote]` |

More in [Shared console](20-shared-console.md).

## Powering off

| Problem | Fix |
|---|---|
| `can't power off: this account isn't allowed ...` | run `./install_power.sh` on the Pi |
| `type /shutdown first, then /shutdown confirm` | the 30 seconds ran out, or someone else made the request: start again |

More in [Powering off](21-powering-off.md).

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

## The Pi freezes, drops off the network, or has to be unplugged

**Is it the start-up rush?** At boot Bob loads the voice, the speech model, the wake word, OpenCV and the camera all
at once. To spread that out, Bob now starts his parts **one at a time**, each waiting until the CPU has calmed
down (the log shows `Starting the voice (CPU 35% busy)`, and so on, ending with `Startup finished`). The microphone,
the heaviest part, comes last. The console is usable straight away, but the voice and the microphone can take a
minute to come up after boot. Under the service, Bob also runs at a lower priority (`Nice=8`) so SSH and the Wi-Fi
stay responsive when he is busy: re-run `./install.sh --service && sudo systemctl daemon-reload` for that. To turn
staggering off, set `[startup] stagger = false`; to make it gentler, lower `calm_cpu_percent` or raise `step_pause_s`.

A Pi that hangs leaves no log when it is unplugged, so set up a recorder **before** it happens:

```bash
cd ~/bob
./install_vitals.sh               # one line every 10 s from boot: load, memory, temperature, power, Wi-Fi, router, whether Bob runs
./install_vitals.sh --watchdog    # optional: a Pi that freezes completely reboots itself after ~15 s (needs a reboot to start)
```

After the next hang, power the Pi back on and read the end of the record:

```bash
tail -60 /var/log/bob-vitals.log
```

| What the last lines show | What it points to |
|---|---|
| `ROUTER-UNREACHABLE` appears first, everything else normal | Wi-Fi dropped, not the Pi: signal, router, or the Wi-Fi power-saving setting |
| `load=` climbing past 5 and `avail=` MB falling toward 0 | overloaded or out of memory: something is using too much (look at what Bob was doing) |
| `throttled=` not `0x0`, or `temp=` over 80 | power supply or heat |
| lines simply stop, all normal until then | the whole Pi froze: the watchdog will now reboot it by itself; a power dip or SD card is likely |
| `bob=0` | Bob had already stopped; check `~/bob/logs/bob.log` |

Also: `sudo journalctl -b -1 -n 100 --no-pager` shows the system log of the previous boot (needs the journal kept across
reboots: `sudo mkdir -p /var/log/journal && sudo systemctl restart systemd-journald` once). Remove the recorder with
`./install_vitals.sh --undo`.
