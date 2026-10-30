# CLAUDE.md: Bob (Claude-driven Raspberry Pi robot)

Read this first. It is the working memory for this repository: what Bob is, how the code is laid out, how to test and ship it, the
decisions already made, and what is and is not verified. Keep it current when something here changes.

## What this is

**Bob** is a small robot (Raspberry Pi 4B, DC motors on a TB6612FNG, camera, mic, speaker, optional HC-SR04 distance sensor, Xbox
controller, Bluetooth speaker) whose mind is a Claude model. A Python program on the Pi (`bob.py`) runs a "tick" loop: take a camera
picture, build a status report, call Claude with tools (drive, speak, look, remember, radio, music, lights, go to a room...), run what it
asks, repeat. People talk to him by voice, console, a shared console, a phone-style web dashboard and the **Bob app** (`app/`, Flutter,
Mac and Android).

- Owner: Adam (the Pi account Bob runs as is `adam`; Mac at `/Users/Adam/Documents/Bob Cena`; the Pi is reachable as `bob`).
- Repo: `github.com/TECWiSaRd/Bob-Cena` (GitHub reports it PUBLIC, so release downloads and the releases API need no login) (branch `main`). Tags: `26.10`, `26.10.1` ("Hindsight"), old `1.0.0`. **26.11 is planned.**
- Friends share one Bob across houses (some with Home Assistant, some without). Another robot, **John**, is a friend's; they talk over a signed radio.
- No licence file on purpose ("no licence for now").

**App updates:** More, App updates checks GitHub's latest release (`app_update.dart`; `appVersion` must equal `pubspec.yaml`'s version and
`version.py`'s `__version__`; a test checks pubspec) and opens the download in the browser. It does not self-install (macOS sandbox; Android
CI builds use a throw-away debug key, so a stable release key is still needed for in-place updates).

**Wiki:** the GitHub wiki is generated from `manuals/` by `tools/make_wiki.py` (published by `.github/workflows/wiki.yml` on every push to
main). Edit the manuals, never the generated wiki pages; hand-made wiki pages and uploads are left alone. A dead link in a manual stops the build.

## Rules that matter most

1. **Safety limits live in code, never in prompts.** Claude can ask for anything; `hardware.Drive` and the overrides decide. Overrides
   (e-stop, /pause, /motion off, sleep, `/speed` cap, distance-sensor reflex) are checked at *action time*. Claude has **no** tool for
   `/shutdown`, `/update`, `/pair`, `/devices`, `/alerts`, quitting, or anything administrative. Tests assert this ("Claude has no way to ...").
2. **Never claim hardware behaviour is verified.** The owner tests everything on the real Pi themselves. Say "tested in simulation / with
   fakes" until they confirm. Offer a short real-Pi checklist per feature.
3. **Don't commit or push unless asked.** When asked: run the tests first, scan the diff for secrets, then commit with the trailer
   `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` and push to `main`. The owner usually says "commit and push".
4. **Secrets never go in the repo**: `.env`, `certs/`, `devices.json`, `usage.json`, `memory.json`, `people.json`, `tuning.json`,
   `config.local.toml`, `logs/`, `.bob-running`, `temp/` are all gitignored. `.env.example` holds placeholders only.
5. **Do not track `temp/`.** The owner keeps the release plan (`temp/26.11.md`) and design references/logos there on purpose. Don't move it.
6. Match the surrounding code (comment density, naming, idiom). Plain, friendly wording in user-facing text and manuals; the audience is
   the owner and non-expert friends.

## Repository map

Python (top level, stdlib + `anthropic`; hardware libs come from apt on the Pi and are imported lazily so tests run on a Mac):

| File | Role |
|---|---|
| `bob.py` | `Controller` (all `/commands` in `handle()`), `main()`, console `/help`, env/tuning loading, startup order |
| `brain.py` | the Claude tick loop, tools, prompts, `Controls` (operator state), `Memory`, `People`, cost accounting |
| `config.py` / `config.toml` / `config.local.toml` | dataclass defaults, shipped safe defaults, the owner's untracked overrides (read after `config.toml`). Unknown keys/sections raise. |
| `hardware.py` | `Drive` (DC/servo, trims, speed cap, estop, reflex), `Camera` (stall guard, watchdog), `Audio` (Piper/espeak) |
| `listen.py` | mic: hands-free/push-to-talk, openWakeWord, faster-whisper, name-mishearing fix ("Mom" to "Bob") |
| `vision.py` / `calibrate.py` / `sensors.py` | follow-me/find-person, turn calibration, distance sensor |
| `home.py` / `tags.py` / `tag_tools.py` | Home Assistant lights, room awareness, AprilTag detection, `/locate`, `/goto` (TagFinder, TagGoer) |
| `stream.py` | HTTP + HTTPS server: MJPEG, web dashboard (`DASH_PAGE`), app API routing, status JSON |
| `appapi.py` / `certs.py` / `bonjour.py` | `/api/v1` handlers, pairing (mutual proofs), device store (hashed tokens), self-signed cert, `_bob._tcp` announcement |
| `access.py` | per-person Wi-Fi-scoped tokens (`TOKEN_NAME`, `WIFI[ssid]=NAME`), lockout |
| `remote.py` / `console.py` | shared console over a unix socket (SO_PEERCRED + groups `bobops`/`bobview`); curses UI; stderr capture |
| `power.py` / `update.py` / `version.py` | two-step `/shutdown`; `/update` from GitHub (git checkout, rollback); code fingerprints |
| `faces.py` | opt-in face recognition (SFace via OpenCV): embeddings only in `faces.json`, two-step `/face remember`, `/face improve`, no Claude tool (manual 26) |
| `alerts.py` | heartbeat (dead man's switch) + ntfy-style push messages; unclean-stop detection |
| `sleepmode.py` / `change.py` / `usage.py` / `startup.py` / `timeline.py` / `index.py` / `selfcheck.py` / `gamepad.py` / `music.py` / `radio.py` | sleep mode; think-only-on-change gate; all-time cost ledger; staggered startup; event timeline; SQLite FTS5 search; `/check`; Xbox controller; Bluetooth/AirPlay; Bluetooth/Wi-Fi robot-to-robot link |

Scripts: `install.sh` (+ `--service`), `install_remote.sh`, `install_power.sh`, `install_music.sh`, `install_vitals.sh` (recorder + hardware
watchdog), `setup_updates.sh` (deploy key + git checkout on the Pi), `deploy.sh` (Mac to Pi; `.rsync-exclude`), `bob.service` (tmux + restart loop).
Docs: `README.md`, `manuals/00..25` (00 is the index), `JOHN_PROMPT.md` (embeds `radio.py`; a test keeps them identical), `TRAINING_HEY_BOB.md`.
Tests: `tests/` (Python), `app/test/` (Dart). CI: `.github/workflows/build-app.yml` (never run yet).

## Running things

Python tests (a Mac venv needs `anthropic`, `numpy`, `opencv-contrib-python-headless`; some tests skip without OpenCV):

```bash
python3 -m venv /tmp/bobtest && /tmp/bobtest/bin/pip install -r requirements.txt numpy opencv-contrib-python-headless
/tmp/bobtest/bin/python -m unittest discover -s tests      # about 460 tests, about 1 minute
```

Flutter (the owner's SDK is at `/Users/Adam/Documents/flutter`; add it to PATH):

```bash
export PATH="$PATH:/Users/Adam/Documents/flutter/bin"
cd app && flutter analyze && BOB_PYTHON=python3 flutter test          # 59 tests; against_python_test.dart starts the REAL Python server
FLUTTER_XCODE_ARCHS=arm64 flutter build macos --release               # the universal build fails on the macOS 27 preview
dart format lib test && dart fix --apply                              # keep analyze clean
```

Android cannot be built on this Mac (no command-line tools); GitHub Actions is meant to build it.
Mac icon: `python3 app/tool/make_mac_icon.py` (needs Pillow); the Liquid Glass `.icon` lives at `app/macos/Runner/AppIcon.icon`.

Deploy to the Pi: `./deploy.sh` (never the old long rsync; it would send the 1 GB `app/` folder and `.git`), then `sudo systemctl restart bob`.
After pulling: `./install.sh --service && sudo systemctl daemon-reload` if `bob.service` changed.

## How the pieces behave (things easy to get wrong)

- **Config layering:** `config.toml` (shipped, everything personal/risky OFF) then `config.local.toml` (owner's) then `tuning.json` (live `/trim`,
  calibration, `tag_min_px`). `save_tuning` must keep other keys (`extra`).
- **Roles** for commands: `owner` (the account Bob runs as; local console), `operator` / `viewer` (shared console groups), `dashboard`
  (web dashboard and app devices). `Controller.handle(line, by=None, role="owner")`. `/shutdown` for `dashboard` is off by default (`[power] who`).
- **Manual drive is per person:** `drive_users` (names; the local console is `"console"`, the Xbox controller is `"gamepad"`);
  `/drive all` means everyone attached at that moment. Leaving or disconnecting removes only that person.
- **Think only on change:** `[brain] think_when = "change"` uses `ChangeGate` (picture change %, distance, mail, heartbeat). Sleep mode uses
  stricter thresholds and blocks the AI's driving.
- **Camera hangs:** `Camera._take` never queues behind a stuck capture; `watch()` fires `camera_stuck` which stops the wheels and, only under
  the service (`BOB_SUPERVISED=1`), exits 75 so the tmux loop restarts Bob.
- **Streaming responses on HTTP/1.1** must end by closing the connection (`close_connection = True`).
- **POST bodies need a Content-Length** (the server refuses chunked). The Dart client sets it explicitly.
- **App security model:** HTTPS with a self-made certificate (pinned by SHA-256 in the app), one-time 12-character pairing code that is never
  sent (HMAC proofs bound to the certificate fingerprint; vectors are shared in `tests/test_app_vectors.py` and `app/test/protocol_test.dart`),
  per-device tokens stored hashed, lockout on bad tries. `/api/v1/*` refuses plain HTTP; the HTTPS port serves nothing else unless a token is set.
- **Status JSON** (`StreamServer.status()`) feeds the web dashboard and the app: mode, auto, follow, sleep, going, usage, vitals, events, rooms,
  room, operators, log. Adding a field means: Python, the Dart reader, a test on each side.
- **`FrameHub.get()` only streams a new picture when the bytes object is new**; test fakes must return fresh objects.
- **Flutter:** fonts are bundled (`app/assets/fonts`, open licences). Widget tests render text as boxes unless fonts are loaded; use
  `AppState(autoConnect: false)` in tests that must not touch the network; the home page is a scroll-driven scene (`home_page.dart`).
  macOS deployment target is 12.0 (Podfile and project).
- **Python tests use fakes, real sockets and a fake Home Assistant**, never hardware. A real unix socket, a real TLS server and a pty run of the
  curses client are used where it matters. Keep that style: write the test with the change.

## Decisions already made (do not re-litigate)

- **Identity (26.11):** people are identified by their **Pi (Linux) username, compared case-insensitively**. The global owner / head admin is the
  account Bob runs as. A name with no matching login may still register as an "app-only" person (warn, don't block); a name that matches a real
  account is that account; an app-only name cannot take a real username without an invite from that user or the owner. Household owners come from
  the existing `.env` mapping (`TOKEN_NAME`, `WIFI[ssid]=NAME`) using usernames.
- **macOS app signing:** "Sign to Run Locally" (ad-hoc), which the owner says supports the Keychain. Verify with a real write/read test in the built
  app and keep a fallback. Friends open the Mac app via System Settings, Privacy & Security, Open Anyway. Android: sideload the APK; Android 17
  developer verification may block unregistered APKs, so `adb install` or the advanced flow (a stable release key is a future improvement).
- **Faces:** Bob remembers a face only when explicitly asked. No automatic enrolment; unknown people are never stored.
- **Fonts and look of the app:** peach `#FFE6CB`, white pill cards, BOB in Rubik Distressed, script greeting, heavy name; emergency stop is
  always on screen (deliberately not in the reference design). Light, Dark and Auto appearance; on/off toggles for AI, follow, sleep, sound,
  camera and emergency stop.
- **Home Assistant** is optional and tied to named Wi-Fi networks (`[home] wifi`), so friends' houses without it are left alone.
- **Updates:** `/update` pulls from GitHub into a git checkout made by `setup_updates.sh` (read-only deploy key); owner only.
- **Branching:** one `main` branch; the app and server share a protocol, so keep them together. Short-lived feature branches for risky work.
- **Future (not 26.11):** Waveshare **ESP32-S3-Matrix** (8x8 WS2812 on GPIO14, QMI8658 IMU, Wi-Fi/BLE, USB-C) as an expression display and
  lift/tilt sensor; keep Bob working without it. Confirm pins on Waveshare's wiki first.

## The 26.11 plan (full text in `temp/26.11.md`, untracked)

"Portable Household Companion + Flagship Intelligence." Foundations: global owner plus Wi-Fi-specific household owners; per-household
profiles (goals, personality, routines, quiet/sleep, approved HA rooms); safe network transitions (stop wheels, switch profile, pause AI);
owner-issued pairing invites binding devices to a principal; device management (list, rename, revoke, claim legacy, recent use); routines
with timezone-aware schedules and no replay after restart; app and console editors; direct pairing over Tailscale; connection diagnostics;
secure credential storage; searchable activity history; safer drive lifecycle; Android parity and CI artifacts. Then **Room Intelligence**
(supported: mapping wizard, named missions on taught routes only, bounded unsupervised missions that are explicitly armed, a guardian that stops
and never self-resumes). Then **Visual Memory** and **Multi-Bob Teamwork** (experimental, opt-in). Suggested order: A identity and devices,
B routines and history, C Room Intelligence, D the two previews. If it slips, ship A+B as 26.11 and C+D as 26.12. Household profiles must never
change hardware pins, safety distances, speed caps, certificates, secrets or e-stop behaviour.

## Status: what is verified and what is not

Verified by tests here (simulation, fakes, real local sockets/TLS, Dart against the real Python server): everything in the repo test suites.

**Not yet verified on the real Pi or devices (the owner will test):** the staggered start and Nice level; `/check` background run; camera
stall guard and self-restart; Wi-Fi radio between two robots; `/goto` and sleep mode; alerts (heartbeat/ntfy); `/update` and
`setup_updates.sh` against real GitHub; the secure app port, Bonjour (avahi) on the Pi, pairing from a real Mac/phone; the Xbox controller
button numbers on the owner's model; think-on-change tuning; the speech-latency timing logs.
**Known open problems:** the Pi sometimes freezes and drops SSH (power-save was on; vitals recorder `install_vitals.sh [--watchdog]` is the
tool to find out why). The GitHub Actions build (`build-app.yml`) has **never run**; Android is untested; Xcode on GitHub runners may be too
old for the Liquid Glass `.icon`. The macOS `flutter build macos --release` universal build fails locally (use the arm64 form).

## Working style that has worked

Small verified steps: write the change, write tests with fakes, run the whole suite, render/inspect UI when it matters (a throwaway test with
fonts loaded can screenshot Flutter screens), then summarise honestly including what was NOT tested. Fix review findings with tests that fail
without the fix. When the owner pastes errors from the Pi, diagnose from the logs first (`logs/bob.log`, `logs/stderr.log`,
`/var/log/bob-vitals.log`, `journalctl -u bob`) and ask for the specific output you need.
