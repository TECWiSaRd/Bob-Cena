# Manual 18: Resources

Where to look things up: Bob's own files, the parts he's built from, the software he uses, and where to
learn more. Web addresses were checked when this was written (October 2026). A few sites (marked †) block
automated checks but work in a normal browser. Sites change, so if one moves, search for its name.

---

## 1. Bob's own files

Everything is in the project folder (`~/bob` on the Pi).

| File or folder | What it is | Manual |
|---|---|---|
| `bob.py` | the main program and every console command | [03](03-console.md) |
| `brain.py` | Claude's instructions, tools and memory | [04](04-brain-and-claude.md), [14](14-memory-and-people.md) |
| `hardware.py` | motors, camera, speaker | [05](05-driving-and-motors.md), [10](10-voice-and-sounds.md) |
| `listen.py` | microphone, speech recognition, wake word | [11](11-microphone-and-wake-word.md) |
| `vision.py`, `calibrate.py` | face finding, follow-me, calibration | [08](08-follow-me.md), [06](06-calibration.md) |
| `sensors.py` | the distance sensor | [09](09-distance-sensor.md) |
| `music.py`, `install_music.sh` | Bluetooth and AirPlay music | [12](12-sound-system.md) |
| `radio.py` | the link to John | [13](13-radio-to-john.md) |
| `stream.py` | the video page and phone dashboard | [07](07-camera-stream-and-dashboard.md) |
| `console.py` | the text screen | [03](03-console.md) |
| `selfcheck.py` | the `/check` report | [03](03-console.md) |
| `tags.py`, `tag_tools.py` | room tags: finding them in the camera picture, and printing them | [19](19-home-assistant.md) |
| `power.py`, `install_power.sh` | powering the Pi off (`/shutdown`) and the one-line permission it needs | [21](21-powering-off.md) |
| `access.py` | per-person dashboard tokens tied to Wi-Fi networks | [07](07-camera-stream-and-dashboard.md) |
| `remote.py`, `install_remote.sh` | the shared console (server, the `bob-console` viewer, and its installer) | [20](20-shared-console.md) |
| `home.py` | the Home Assistant lights and Bob's room | [19](19-home-assistant.md) |
| `timeline.py`, `index.py` | the event record and its search index | [14](14-memory-and-people.md) |
| `tests/` | automatic checks for the safety-critical code | the README, "Tests" |
| `config.py`, `config.toml` | settings and their defaults | [15](15-settings-reference.md) |
| `install.sh` | installs everything on the Pi | [02](02-installing-and-updating.md) |
| `bob.service` | starts Bob at boot | [02](02-installing-and-updating.md) |
| `.env` (Pi only) | API key and passwords. **Never share it** | [15](15-settings-reference.md) |
| `tuning.json`, `memory.json`, `people.json` (Pi only) | saved tuning, notes, people | [14](14-memory-and-people.md) |
| `logs/bob.log` (Pi only) | the full log | [03](03-console.md) |
| `wakewords/` | wake word models (`hey_bob.onnx`) | [11](11-microphone-and-wake-word.md) |
| `voices/` (Pi only) | Piper voice files | [10](10-voice-and-sounds.md) |
| `TRAINING_HEY_BOB.md` | training a better wake word | [11](11-microphone-and-wake-word.md) |
| `JOHN_PROMPT.md` | the message that sets up John's side of the radio | [13](13-radio-to-john.md) |
| `README.md` | the short overview | |

---

## 2. Parts and where to learn about them

| Part | Learn more |
|---|---|
| Raspberry Pi 4B | Raspberry Pi documentation †: https://www.raspberrypi.com/documentation/ |
| Pi pin numbers | an interactive pin chart: https://pinout.xyz |
| Pi operating system and SD card writer | Raspberry Pi Imager †: https://www.raspberrypi.com/software/ |
| Pi camera module | Camera software guide †: https://www.raspberrypi.com/documentation/computers/camera_software.html |
| `/boot/firmware/config.txt` (the PWM line) | Configuration guide †: https://www.raspberrypi.com/documentation/computers/configuration.html |
| TB6612FNG motor driver | SparkFun's hookup guide: https://learn.sparkfun.com/tutorials/tb6612fng-hookup-guide |
| GPIO from Python (`gpiozero`) | https://gpiozero.readthedocs.io |
| Camera from Python (`picamera2`) | https://picamera.readthedocs.io |
| HC-SR04 distance sensor | search "HC-SR04 Raspberry Pi voltage divider": you need two resistors on ECHO ([manual 09](09-distance-sensor.md)) |
| Yellow TT gear motors | search "TT motor 3-6V gearbox": the motors are the same kind used in many beginner robots |

[Manual 01](01-hardware-and-wiring.md) has Bob's full parts list and what each part does.

---

## 3. Software Bob is built on

| Piece | What it does for Bob | Where |
|---|---|---|
| **Claude API** | Bob's brain | docs: https://platform.claude.com/docs<br>keys and billing: https://console.anthropic.com |
| **Piper** | natural speech | https://github.com/rhasspy/piper<br>all voices: https://huggingface.co/rhasspy/piper-voices |
| **faster-whisper** | turns speech into text | https://github.com/SYSTRAN/faster-whisper |
| **openWakeWord** | listens for "Hey Bob" | https://github.com/dscripka/openWakeWord |
| openwakeword.com | where the "Hey Bob" model came from | https://openwakeword.com |
| **OpenCV** and **YuNet** | finds faces for follow-me | YuNet model: https://github.com/opencv/opencv_zoo |
| **PipeWire** | mixes speech and music | https://docs.pipewire.org |
| **BlueZ** | Bluetooth on Linux | https://github.com/bluez/bluez |
| **shairport-sync** | the AirPlay receiver | https://github.com/mikebrady/shairport-sync |
| **Home Assistant** | the lights | REST API: https://developers.home-assistant.io/docs/api/rest/<br>access tokens: https://www.home-assistant.io/docs/authentication/<br>areas: https://www.home-assistant.io/docs/organizing/areas/ |
| AprilTag | the printed room tags | https://april.eecs.umich.edu/software/apriltag |
| OpenCV aruco module | what reads the tags | search "OpenCV ArUco marker detection" (the official docs block automatic checks †) |
| ESPHome Bluetooth proxy, Bermuda | room tracking from Bluetooth | https://esphome.io/components/bluetooth_proxy.html<br>https://github.com/agittins/bermuda |
| **Tailscale** | the fixed `bob` name from anywhere | https://tailscale.com/kb |
| **SQLite full-text search** | the search index | https://www.sqlite.org/fts5.html |
| **Google Colab** | free computer for training a wake word | https://colab.research.google.com |

---

## 4. Tools for the person at the keyboard

| You need | Where |
|---|---|
| **Windows**: a terminal with SSH built in | Windows Terminal: https://learn.microsoft.com/en-us/windows/terminal/ |
| **Mac**: a terminal | the built-in Terminal app (Applications → Utilities) |
| A refresher on `ssh` keys | https://ubuntu.com/tutorials/ssh-keygen-on-windows (works for any system) |
| A `tmux` cheat sheet | https://tmuxcheatsheet.com |

---

## 5. Cheat sheets

### The commands you'll use ninety percent of the time

| Want to... | Type |
|---|---|
| Power the Pi off | `/shutdown`, then `/shutdown confirm` |
| **Stop everything** | **Space** (empty line), or `/estop` |
| Let Bob move again after a stop | `/clear`, then `/resume` |
| Stop him thinking (and spending) | `/pause` |
| Let him think and act | `/resume` |
| Check he's healthy | `/check` |
| Make him talk to you | `/ask hello Bob` |
| Drive by hand | `/drive`, then W A S D (X to leave) |
| Cheaper testing | `/model haiku` |
| See what he remembers | `/notes`, `/people` |
| Tell him which room he's in | `/where kitchen` |
| Test a room tag | `/tags` |
| Set how close a tag must be | `/tags min` (facing a tag, at the farthest distance you want) |
| Make him look for his room | `/locate` |
| See who's attached | `/who` |
| See which dashboard tokens work here | `/access` |
| Find anything he recorded | `/search lens covered` |
| Turn the camera off | `/camera off` |
| Silence him | `/mute` |
| Shut down | `/quit` |

### Linux commands used in these manuals

| Command | What it does |
|---|---|
| `ssh user@bob` | opens a session on the Pi |
| `cd ~/bob` | goes to Bob's folder |
| `tmux new -s bob` | starts a session that survives disconnecting |
| `tmux attach -t bob` | reconnects to it |
| `Ctrl-B`, then `D` | leaves tmux with Bob still running |
| `tail -50 ~/bob/logs/bob.log` | the last 50 log lines |
| `hostname -I` | shows the Pi's address |
| `nano <file>` | edits a file (`Ctrl-O`, Enter to save; `Ctrl-X` to leave) |
| `sudo reboot` / `sudo shutdown now` | restarts / powers down the Pi. Shut down before pulling power |
| `.venv/bin/python bob.py` | runs Bob (the `.venv` is his own Python) |

### Which manual?

| I want to... | Read |
|---|---|
| run Bob for the first time | [00](00-START-HERE.md) |
| connect from my computer | [02](02-installing-and-updating.md) |
| stop him safely | [16](16-safety.md) |
| something is broken | [17](17-troubleshooting.md) |
| change a setting | [15](15-settings-reference.md) |

---

## 6. Getting help

1. Look in [manual 17](17-troubleshooting.md) first. Most problems are there.
2. Read the log. Bob explains most failures in plain words.
3. Ask whoever set Bob up. Give them the exact error, what you did just before it, and the status bar line.
4. For a problem in one of the pieces above (not Bob's own code), the project's page in section 3 has an
   issues list.

Never send anyone your `.env` file, API key, `BOB_STREAM_TOKEN`, `BOB_RADIO_SECRET` or AirPlay password.
