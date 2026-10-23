# Manual 02: Installing and updating

This manual covers getting Bob's software onto the Pi, keeping it up to date, connecting to it from your
Mac, and starting Bob automatically when the Pi powers on.

**Where things live:**
- **On your Mac:** the project folder `~/Documents/Bob Cena`. This is the master copy. Make all code and
  settings changes here.
- **On the Pi:** a copy in `~/bob`. You copy the Mac's folder over whenever something changes.

---

## Part 1: Connecting to the Pi

### First-time Pi setup

When you flash the SD card with **Raspberry Pi Imager**, click **Edit settings** and set:
- a **hostname** (for example `bob`),
- a **username and password** (these manuals use `adam`; use yours),
- your **Wi-Fi** name and password,
- on the **Services** tab, **enable SSH**.

### Connecting with SSH

From the Mac's Terminal:

```bash
ssh adam@bob                 # if you use Tailscale (recommended, see below)
ssh adam@192.168.x.x        # or the Pi's local address
```

Find the Pi's address on the Pi with `hostname -I` (capital I), or in your router's device list. The
first time you connect, type `yes` to trust the Pi.

### Tailscale (recommended)

Tailscale gives the Pi a fixed name (`bob`) that works from anywhere, so you never have to chase a
changing IP address again. It's already set up on your Pi. To set it up on a new Pi:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up            # open the link it prints, and sign in
```

Install the Tailscale app on your Mac with the same account. In the Tailscale admin page, **turn off key
expiry** for the Pi, or it drops off every few months.

### Keeping Wi-Fi responsive

The Pi's Wi-Fi power saving caused the SSH timeouts you hit earlier. To turn it off permanently:

```bash
sudo nmcli connection modify "$(nmcli -t -f NAME connection show --active | head -1)" 802-11-wireless.powersave 2
```

---

## Part 2: Copying the code to the Pi

Run this **on your Mac** whenever anything changes. It only sends files that changed:

```bash
rsync -av --exclude '.venv' --exclude 'logs' --exclude '__pycache__' \
  ~/Documents/"Bob Cena"/ adam@bob:~/bob/
```

- The `/` after `"Bob Cena"` matters: it copies the folder's *contents* into `~/bob`.
- The first copy works exactly the same way.

**What a copy overwrites, and what it never touches:**

| Overwritten by every copy (edit these on the Mac) | Lives only on the Pi (never overwritten) |
|---|---|
| all `.py` files, `install.sh`, `install_music.sh` | `.env` (your API key and passwords) |
| `config.toml` (your settings) | `tuning.json` (`/trim`, `/minduty`, calibration) |
| the `manuals/` folder | `memory.json` (Bob's notes), `people.json`, `usage.json` (the all-time cost count) |
| `wakewords/` (your wake word model) | `logs/`, `captures/`, `voices/`, `models/`, `sounds/`, `.venv/` |

**Your own settings go in `config.local.toml`** (next to `config.toml`). It is read after `config.toml`, wins over it, and
is never committed to git, so the shared `config.toml` keeps its safe defaults (timeline, Home Assistant, shared console and
the AI search all off). Copy only the lines you change, for example:

```toml
[home]
enabled = true
rooms = ["Kitchen"]
```

**Important:** if you change `config.toml` on the Pi, the next copy from the Mac replaces it. Make
settings changes on the Mac, or make the same change in both places.

After copying, **restart Bob** so he uses the new code: type `/quit` in his console, then start him again.
If he runs as a service, use `sudo systemctl restart bob`.

---

## Part 3: Installing (first time, or after big changes)

On the Pi:

```bash
cd ~/bob
./install.sh
```

It takes 10-20 minutes and asks for your password for the system parts. It's safe to run again: it only
adds what's missing and never touches your `.env`, notes or settings.

**What it does, in order:**

| Step | What it installs or changes | If it fails |
|---|---|---|
| System packages | Python tools, camera support (picamera2), GPIO, OpenCV, espeak-ng, ALSA tools, tmux | stops: fix and re-run |
| Hardware PWM | adds the `pwm-2chan` line to `/boot/firmware/config.txt` | **reboot afterwards** if it says it added it |
| pigpio | an optional servo helper | skipped quietly on newer Pi OS (not needed) |
| Python environment | creates `.venv` with the Claude SDK | stops: fix and re-run |
| Speech recognition | faster-whisper and its `tiny.en` model | `!!` warning; the microphone feature is unavailable |
| Wake word | openWakeWord 0.6+ and its "hey jarvis" model | `!!` warning; Bob listens for the word "bob" instead |
| Face detector | the YuNet model into `models/` (checked against a checksum) | `!!` warning; following uses an older detector |
| Voice | Piper and the `en_US-lessac-medium` voice | `!!` warning; Bob speaks with espeak-ng |
| `.env` | creates it from `.env.example` if missing; makes it private | |

Read the output for lines starting with `!!`. Each one is an optional piece that didn't install, and
says what Bob does instead.

**If your SSH connection might drop** during the long download:

```bash
nohup ./install.sh > install.log 2>&1 &
tail -f install.log          # Ctrl-C stops watching, not the install
```

### Your API key and passwords (`.env`)

```bash
nano ~/bob/.env
```

| Line | Needed for |
|---|---|
| `ANTHROPIC_API_KEY=sk-ant-...` | **required**: Bob's brain |
| `BOB_STREAM_TOKEN=...` | optional: a password for the camera page; **required** for the phone dashboard (8+ characters) |
| `BOB_RADIO_SECRET=...` | optional: the shared secret for the radio link to John |

Save with `Ctrl-O`, Enter, then `Ctrl-X`. Never paste these values into a chat or a public place.

### The music system (separate, optional)

Bluetooth and AirPlay music has its own installer, because it changes system audio services. See
[manual 12](12-sound-system.md):

```bash
./install_music.sh
```

---

## Part 4: Running Bob

### By hand (recommended while you're testing)

```bash
cd ~/bob
tmux new -s bob                       # a session that survives disconnects
.venv/bin/python bob.py --paused      # start with the AI paused
```

- **Leave Bob running and disconnect:** `Ctrl-B`, then `D`, or type `/detach` in his console.
- **Come back later:** `tmux attach -t bob`.
- **Stop Bob:** type `/quit` in his console.

**Start-up options:**

| Option | What it does |
|---|---|
| `--paused` | starts with the AI paused, so nothing moves until you type `/resume` (**recommended**) |
| `--sim` | simulates all hardware: test the console and AI anywhere, even on a Mac |
| `--headless` | no console screen: the log prints as plain text and commands are read line by line |
| `--debug` | extra detail in the log |
| `--config FILE` | use a different settings file |

### Automatically at power-on

```bash
cd ~/bob
./install.sh --service
sudo systemctl start bob
tmux attach -t bob          # open his console
```

The service starts Bob inside a tmux session called `bob` at every boot, and restarts him if he crashes
(a clean `/quit` ends it). Useful commands:

| Command | Effect |
|---|---|
| `sudo systemctl stop bob` | stop Bob |
| `sudo systemctl restart bob` | restart after copying new code |
| `sudo systemctl disable bob` | stop starting at boot |
| `journalctl -u bob` | the service's own messages |

**Note:** with the service, Bob starts with the AI *running*, unless you set `start_paused = true`
under `[brain]` in `config.toml`. Consider doing that.

---

## Part 5: Backing up what lives only on the Pi

Bob's notes, the people he knows, your tuning and your passwords exist only on the Pi. To keep a copy on
your Mac:

```bash
rsync -av adam@bob:~/bob/{memory.json,people.json,tuning.json,usage.json,.env} ~/Documents/bob-backup/
```

Keep that backup folder private: it contains your API key.

## Part 6: After a power cut or a crash

Pulling the power is usually harmless, but if it happened during an install:

```bash
sudo dpkg --configure -a
sudo apt-get -f install -y
cd ~/bob && rm -rf .venv && ./install.sh
```

Check the SD card is healthy with `dmesg | grep -i -E "error|corrupt"`: a few "recovering journal" lines
are normal; repeated I/O errors mean the card needs replacing.

## Troubleshooting

| Problem | Fix |
|---|---|
| `ssh: Could not resolve hostname` | use the IP address, or check Tailscale is connected on both machines |
| SSH times out but the Pi is on | the Mac and Pi are on different networks, or Wi-Fi power saving: see Part 1 |
| `Permission denied` running `./install.sh` | `chmod +x install.sh` (copying can drop the "executable" flag) |
| `!!` lines in the install output | that optional piece is missing; the line says what Bob does instead |
| `openWakeWord is missing or too old` | `.venv/bin/pip install --no-deps --upgrade 'openwakeword>=0.6'` |
| Bob ignores a settings change | you edited the Pi's copy and a later `rsync` replaced it, or Bob wasn't restarted |
| `tmux: command not found` | `sudo apt-get install -y tmux` (install.sh normally does this) |

More: [Troubleshooting](17-troubleshooting.md).
