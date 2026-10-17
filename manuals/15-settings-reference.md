# Manual 15: Settings reference

Every setting Bob has, in one place. Most live in **`config.toml`**. Passwords live in **`.env`**. Tuning you
do from the console is saved in **`tuning.json`**.

---

## How settings work

**Where a value comes from**, in order (later ones win):

1. The built-in default (in `config.py`).
2. `config.toml`. Anything you leave out uses the default.
3. `tuning.json` on the Pi, for `left_trim`, `right_trim`, `dc_min_duty` and calibration results.
4. Console commands such as `/speed` or `/model`, until Bob restarts.

**Editing `config.toml`:**
- **Edit it on your Mac**, then copy the project over and restart Bob. A copy from the Mac replaces the Pi's
  version, so changes made only on the Pi get lost.
- Text goes in double quotes: `model = "claude-opus-5-5"`.
- `true` and `false` are lower case, without quotes.
- A setting that's a decimal number can be written without a decimal point (`max_speed = 1` is fine), but
  whole-number settings must stay whole (`port = 8080`, not `8080.0`).
- Lines starting with `#` are comments.
- **A misspelled setting stops Bob from starting**, with a message naming it, such as
  `unknown setting [drive] max_sped`. The same goes for a misspelled `[section]` and for a word that isn't
  allowed, such as `type = "dcc"` (it must be `"dc"` or `"servo"`). That's deliberate, so typos don't go unnoticed.

**Your settings that differ from the defaults** are marked ★ below.

---

## `[drive]`: motors and movement

See [Driving and motors](05-driving-and-motors.md).

| Setting | Default | What it does |
|---|---|---|
| `type` | `"dc"` | `"dc"` = DC motors on a TB6612FNG; `"servo"` = continuous-rotation servos |
| `max_speed` | 0.8 | the speed cap, from 0 to 1. Every movement is scaled by it. Live: `/speed` |
| `max_move_seconds` | 3.0 | the longest any single movement can last |
| `left_invert` | false | reverse the left wheel's direction |
| `right_invert` | true | reverse the right wheel's direction (motors are mirrored, so one side is usually reversed) |
| `left_trim` | 0.0 | drift fix. DC: +0.05 = left wheel 5% faster. Servo: shifts the pulse. Live: `/trim` |
| `right_trim` | 0.0 | the same for the right wheel |
| `dc_left_pwm` | 12 | GPIO for the driver's PWMA (left speed) |
| `dc_left_in1` | 5 | GPIO for AIN1 (left direction) |
| `dc_left_in2` | 6 | GPIO for AIN2 (left direction) |
| `dc_right_pwm` | 13 | GPIO for PWMB (right speed) |
| `dc_right_in1` | 16 | GPIO for BIN1 (right direction) |
| `dc_right_in2` | 20 | GPIO for BIN2 (right direction) |
| `dc_standby` | 21 | GPIO for STBY. Bob pulls it low on an emergency stop, cutting both motors |
| `dc_pwm_hz` | 20000 | how fast the motor power switches. Above hearing, so no whine |
| `dc_min_duty` | 0.25 | the lowest power that actually turns the wheels. Live: `/minduty` |
| `dc_brake` | true | `true` = stopped motors resist turning; `false` = they coast |
| `estop_button_pin` | -1 | GPIO of a physical stop button (to ground). -1 = none |
| `pwm` | `"auto"` | servo only: `"auto"`, `"hardware"`, `"pigpio"` or `"software"` |
| `left_pin`, `right_pin` | 12, 13 | servo only: GPIO for each servo's signal wire |
| `min_pulse_ms`, `max_pulse_ms` | 1.0, 2.0 | servo only: the pulse lengths for full reverse and full forward |

## `[camera]`

See [Camera, stream and dashboard](07-camera-stream-and-dashboard.md).

| Setting | Default | What it does |
|---|---|---|
| `source` | `"auto"` | `"auto"` (camera module first, then USB), `"csi"` or `"usb"` |
| `device` | 0 | USB only: the N in `/dev/videoN` |
| `width`, `height` | 640, 480 | picture size |
| `jpeg_quality` | 80 | picture compression, 1-100 |
| `rotate_180` | false | turn the picture upside down (for a camera mounted that way) |
| `fov_deg` | 62.0 | the camera's horizontal field of view in degrees. Used by following and calibration |

## `[stream]`: video and dashboard

| Setting | Default | What it does |
|---|---|---|
| `enabled` | true | the web server for video and the dashboard |
| `host` | `"0.0.0.0"` | `"0.0.0.0"` = reachable on your network, but only when `BOB_STREAM_TOKEN` is set (without one Bob uses `"127.0.0.1"` and logs a warning); `"127.0.0.1"` = only through an SSH tunnel |
| `port` | 8080 | the port in the web address |
| `fps` | 10.0 | video pictures per second |
| `dashboard` | true | the phone control page. Only works with `BOB_STREAM_TOKEN` (8+ characters) in `.env` |

## `[sensor]`: distance sensor

See [Distance sensor](09-distance-sensor.md).

| Setting | Default | What it does |
|---|---|---|
| `enabled` | false | switch the HC-SR04 on |
| `trigger_pin` | 23 | GPIO for TRIG |
| `echo_pin` | 24 | GPIO for ECHO (through a voltage divider!) |
| `stop_cm` | 15 | forward moves are refused or stopped inside this distance. Live: `/range stop` |
| `max_cm` | 200 | readings beyond this count as "clear" |

## `[follow]`: follow me

See [Follow me](08-follow-me.md).

| Setting | Default | What it does |
|---|---|---|
| `distance_m` | 1.0 | how far from the person to stay |
| `max_speed` | 0.5 | top speed while following (the overall cap still applies) |
| `max_seconds` | 60.0 | the longest single follow |
| `lost_after_s` | 3.0 | give up this long after losing the face |
| `turn_gain` | 0.9 | how strongly he turns toward the person. Lower it if he swings side to side |
| `forward_gain` | 2.5 | how strongly he closes the distance. Lower it if he lurches |
| `deadzone` | 0.12 | how far off-centre still counts as "straight ahead" (0 = centre, 1 = edge) |

## `[audio]`: voice

See [Voice and sounds](10-voice-and-sounds.md).

| Setting | Default | What it does |
|---|---|---|
| `tts` | `"piper"` | `"piper"` (natural voice) or `"espeak-ng"` (robotic). Falls back to espeak-ng automatically |
| `piper_model` | `"en_US-lessac-medium"` | Piper voice name (in `voices/`) or a path to a `.onnx` voice |
| `voice` | `"en-us"` | espeak-ng voice (fallback only) |
| `speed_wpm` | 165 | espeak-ng speed in words per minute (fallback only) |
| `device` | `""` | sound output for `aplay`; empty = the Pi's default |
| `player` | `"auto"` | `"auto"`, `"pw-play"` or `"aplay"`. Auto uses PipeWire when it's running, so speech mixes with music |

## `[mic]`: microphone and wake word

See [Microphone and wake word](11-microphone-and-wake-word.md).

| Setting | Default | What it does |
|---|---|---|
| `enabled` | false | start listening when Bob starts |
| `mode` | `"hands-free"` | `"hands-free"` or `"push-to-talk"` |
| `device` | `""` | ★ yours: `"plughw:CARD=Device,DEV=0"`. The microphone (`arecord -l` lists them) |
| `model` | `"tiny.en"` | speech recognition model: `"tiny.en"` (fast) or `"base.en"` (better, slower) |
| `language` | `"en"` | the language you speak |
| `threshold` | 0.02 | loudness (0-1) that counts as speech |
| `silence_ms` | 800 | this much quiet ends a sentence |
| `max_seconds` | 15.0 | the longest single recording |
| `after_speech_s` | 1.0 | deaf this long after Bob stops talking |
| `pause_while_driving` | true | deaf while the wheels turn |
| `cpu_threads` | 3 | processor cores speech recognition may use (the Pi has 4) |
| `wake_engine` | `"openwakeword"` | `"openwakeword"` (audio model), `"text"` (look for the word in the transcript) or `"off"` |
| `wake_model` | `"hey_jarvis"` | ★ yours: `"wakewords/hey_bob.onnx"`. A pretrained word (`hey_jarvis`, `alexa`, `hey_mycroft`, `hey_rhasspy`) or a model file |
| `wake_threshold` | 0.5 | how sure the wake word model must be (0-1) |
| `wake_word` | `"bob"` | the word for the `"text"` engine |
| `wake_window_s` | 20.0 | after waking, listen this long without needing the wake word again |
| `wake_confirm` | false | ★ yours: `true`. Double-check the name appears in the transcript |
| `wake_verifier` | `""` | experimental: a filter trained on your own voice |

## `[radio]`: link to John

See [Radio to John](13-radio-to-john.md).

| Setting | Default | What it does |
|---|---|---|
| `enabled` | false | switch the radio on (also needs `BOB_RADIO_SECRET`) |
| `name` | `"Bob"` | this robot's name |
| `peer_name` | `"John"` | the other robot's name |
| `role` | `"listen"` | `"listen"` (wait) or `"connect"` (call) |
| `peer_address` | `""` | the other robot's Bluetooth address, for `"connect"` |
| `channel` | 3 | Bluetooth channel; the same on both robots |
| `ai_max_per_minute` | 6 | messages Claude may send per minute |

## `[music]`: Bluetooth and AirPlay

See [Sound system](12-sound-system.md).

| Setting | Default | What it does |
|---|---|---|
| `enabled` | false | switch the music system on (run `install_music.sh` first) |
| `bluetooth` | true | allow Bluetooth music |
| `airplay` | true | allow AirPlay music |
| `airplay_bus` | `"session"` | where the AirPlay receiver's controls are (leave as is) |
| `exclusive` | true | the newest source pauses the older one |
| `initial_volume` | 0.5 | each new music stream starts at this volume (0-1) |
| `max_volume` | 0.85 | the most Bob or the console may set |
| `duck_level` | 0.25 | music volume while Bob talks, as a fraction |
| `duck_hold_s` | 0.8 | how long after Bob stops talking the music returns |
| `mic_deaf_while_playing` | true | the microphone ignores the room while music plays |
| `poll_seconds` | 1.0 | how often Bob checks what's playing |

## `[brain]`: Claude

See [The brain](04-brain-and-claude.md).

| Setting | Default | What it does |
|---|---|---|
| `model` | `"claude-opus-5-5"` | which Claude model. Others: `"claude-sonnet-5-5"`, `"claude-haiku-5-5"`. Live: `/model` |
| `effort` | `"low"` | how hard Claude thinks per request: `"low"`, `"medium"`, `"high"`, `"xhigh"`, `"max"`. Live: `/effort` |
| `max_tokens` | 16000 | the longest response Claude may give in one request |
| `tick_seconds` | 2.0 | pause between thinking rounds. Longer = cheaper |
| `max_steps_per_tick` | 8 | how many rounds of tools Claude may use in one tick |
| `fallbacks` | true | if a request is declined, the API retries on another model (Opus and Sonnet only) |
| `start_paused` | false | start with the AI paused. Recommended `true` if Bob starts at boot |
| `goal` | explore carefully, be friendly | Bob's mission. Live: `/goal` |

---

## `.env`: private keys and passwords

On the Pi only, readable only by you. Edit with `nano ~/bob/.env`, then restart Bob.

| Line | Needed for |
|---|---|
| `ANTHROPIC_API_KEY=` | **required**: your Claude API key |
| `BOB_STREAM_TOKEN=` | a password for the video page; needed (8+ characters) for the dashboard |
| `BOB_RADIO_SECRET=` | the radio link to John (16+ characters, identical on both robots) |

`BOB_AIRPLAY_PASSWORD` isn't in `.env`: it's given to `install_music.sh` when you run it.

## `tuning.json`: saved tuning

Written by Bob on the Pi. You don't normally edit it.

| Key | Set by | Limits |
|---|---|---|
| `left_trim`, `right_trim` | `/trim`, `/calibrate straight` | -0.5 to 0.5 |
| `dc_min_duty` | `/minduty` | 0 to 0.9 |
| `calibration` | `/calibrate turn` | measured turn rates and the speed cap they were measured at |

Delete `tuning.json` to go back to the `config.toml` values. If it's damaged, Bob ignores it and logs a warning.
