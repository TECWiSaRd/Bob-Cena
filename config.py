"""Configuration: dataclass defaults, overridden by config.toml."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass
class DriveConfig:
    type: str = "dc"             # "dc" (TB6612FNG + DC motors) or "servo" (continuous-rotation servos)
    pwm: str = "auto"            # servo only: auto | hardware | pigpio | software
    left_pin: int = 12           # BCM numbering
    right_pin: int = 13
    left_invert: bool = False    # servos are mirrored, so one side is usually inverted
    right_invert: bool = True
    left_trim: float = 0.0       # drift fix. DC: speed scale (+0.05 = that wheel 5% faster); servo: pulse shift
    right_trim: float = 0.0
    min_pulse_ms: float = 1.0
    max_pulse_ms: float = 2.0
    max_speed: float = 0.8       # hard cap applied to every command (0-1)
    max_move_seconds: float = 3.0
    # --- DC motors on a TB6612FNG (type = "dc"); BCM pin numbers ---
    dc_left_pwm: int = 12        # PWMA. GPIO12/13 use hardware PWM if the overlay is enabled
    dc_left_in1: int = 5         # AIN1
    dc_left_in2: int = 6         # AIN2
    dc_right_pwm: int = 13       # PWMB
    dc_right_in1: int = 16       # BIN1
    dc_right_in2: int = 20       # BIN2
    dc_standby: int = 21         # STBY: low cuts both motors; Bob drops it on E-stop
    dc_pwm_hz: int = 20000       # above hearing; software-PWM fallback is capped at 1 kHz
    dc_min_duty: float = 0.25    # lowest duty at which your motors actually turn
    dc_brake: bool = True        # stopped motors resist turning (False = coast)
    estop_button_pin: int = -1   # optional physical E-stop button to GND; -1 = none


@dataclass
class CameraConfig:
    source: str = "auto"         # "auto" (ribbon module, then USB), "csi" or "usb"
    device: int = 0              # USB camera: N for /dev/videoN (see v4l2-ctl --list-devices)
    width: int = 640
    height: int = 480
    jpeg_quality: int = 80
    rotate_180: bool = False
    restart_after_s: float = 15.0   # if the camera driver hangs this long, stop the wheels and restart Bob (0 = never). Needs the service
    fov_deg: float = 62.0        # horizontal field of view: Pi Camera v2 ~62, Camera Module 3 ~66, most webcams 60-78


@dataclass
class StreamConfig:
    enabled: bool = True
    host: str = "0.0.0.0"        # use "127.0.0.1" to keep it local (e.g. behind an SSH tunnel)
    port: int = 8080
    fps: float = 10.0
    dashboard: bool = True       # phone control page at /dash; only active when BOB_STREAM_TOKEN is set
    https: bool = True           # the Bob app's secure port (a certificate is made on first start; pair with /pair). Needs openssl
    https_port: int = 8443
    bonjour: bool = True         # announce Bob on the local network so the app can find him (needs avahi-utils on the Pi)


@dataclass
class SensorConfig:
    enabled: bool = False        # the obstacle reflex: needs at least one of the sensors below (see sensors.py for wiring)
    ultrasonic: bool = True      # the HC-SR04 ultrasonic sensor
    tof: bool = False            # a VL53L1X laser sensor on I2C (needs: pip install vl53l1x, and I2C switched on)
    tof_bus: int = 1             # the Pi's I2C bus number
    tof_address: int = 0x29      # the VL53L1X's usual address
    trigger_pin: int = 23
    echo_pin: int = 24           # through a 1k/2k voltage divider: the sensor's ECHO is 5 V!
    stop_cm: int = 15            # the wheels refuse to go forward when something is closer than this
    max_cm: int = 200


@dataclass
class FollowConfig:
    distance_m: float = 1.0      # how far from the person Bob tries to stay (estimated from the size of their face)
    max_speed: float = 0.5       # top speed while following (the drive speed cap still applies on top)
    max_seconds: float = 60.0    # longest single follow session
    lost_after_s: float = 3.0    # give up this long after the face disappears
    turn_gain: float = 0.9
    forward_gain: float = 2.5
    deadzone: float = 0.12       # ignore a person this close to the centre line (0 = centre, 1 = frame edge)
    scan_speed: float = 0.35     # /find and find_person: how fast Bob turns on the spot while looking for a face
    scan_seconds: float = 25.0   # ... and how long he looks before giving up


@dataclass
class AudioConfig:
    tts: str = "piper"           # "piper" (natural; falls back to espeak-ng if unavailable) or "espeak-ng"
    piper_model: str = "en_US-lessac-medium"  # voice name (in voices/) or a path to a .onnx file
    voice: str = "en-us"         # espeak-ng voice
    speed_wpm: int = 165         # espeak-ng speed
    device: str = ""             # aplay -D device; empty = system default
    player: str = "auto"         # "auto" (pw-play if PipeWire is running, else aplay), "pw-play" or "aplay". Needed so Bob's voice mixes with music


@dataclass
class MicConfig:
    enabled: bool = False        # start listening at boot (off by default: it is an always-on microphone)
    mode: str = "hands-free"     # "hands-free" (voice detection) or "push-to-talk" (Tab / /talk in the console)
    device: str = ""             # arecord -D device, e.g. "plughw:1,0" (see: arecord -l); empty = default
    model: str = "tiny.en"       # faster-whisper model: tiny.en (fastest), base.en (more accurate, ~2-3x slower)
    language: str = "en"
    threshold: float = 0.02      # loudness (0-1) that counts as speech; /listen shows the live level
    silence_ms: int = 800        # this much quiet ends an utterance
    max_seconds: float = 15.0    # longest single utterance
    after_speech_s: float = 1.0  # stay deaf this long after Bob stops talking (avoids hearing himself)
    pause_while_driving: bool = True  # motor noise would be transcribed as garbage
    cpu_threads: int = 3         # leave one of the Pi's four cores for everything else
    # --- wake word (hands-free mode only; push-to-talk never needs one) ---
    wake_engine: str = "openwakeword"  # "openwakeword" (audio model), "text" (match the transcript) or "off" (hear everything)
    wake_model: str = "hey_jarvis"     # pretrained: hey_jarvis, alexa, hey_mycroft, hey_rhasspy; or a path to a trained .onnx
    wake_threshold: float = 0.5        # 0-1; raise if it triggers by accident, lower if it misses you
    name_aliases: list = field(default_factory=lambda: ["mom", "bub", "bop", "mob", "bomb", "bobb"])   # what Whisper mishears the name as; fixed back to the name when it starts what you say
    initial_prompt: str = ""           # a hint to the speech model; empty = "The speaker is talking to a robot named Bob." (helps it hear the name)
    wake_word: str = "bob"             # for wake_engine = "text" (and the fallback if openwakeword isn't installed)
    wake_window_s: float = 20.0        # after waking, Bob keeps listening this long without needing the wake word again
    wake_verifier: str = ""            # a voice-specific verifier you trained with wakeword_tools.py (see README); empty = none
    wake_confirm: bool = False         # after the audio model fires, also check the transcript contains the name (cuts false wakes from look-alike words)


@dataclass
class RadioConfig:
    enabled: bool = False        # also needs BOB_RADIO_SECRET in .env (the same text on both robots)
    name: str = "Bob"            # this robot's name
    peer_name: str = "John"      # the other robot's name
    role: str = "listen"         # "listen" (wait for the other robot) or "connect" (call it): one of each
    transport: str = "bluetooth" # "bluetooth" or "wifi" (the same signed messages over your network or a VPN such as Tailscale)
    peer_address: str = ""       # the other robot's Bluetooth address, or (wifi) its host name or IP address; needed for role = "connect"
    channel: int = 3             # Bluetooth only: RFCOMM channel (1-30); both robots must use the same one
    port: int = 8765             # Wi-Fi only: the TCP port the listening robot opens; both robots must use the same one
    bind: str = "0.0.0.0"        # Wi-Fi only, for the listening robot: which address to listen on ("0.0.0.0" = every network)
    ai_max_per_minute: int = 6   # most messages Claude may send per minute (keeps robot chatter cheap)


@dataclass
class MusicConfig:
    enabled: bool = False        # a Bluetooth speaker + AirPlay receiver (run install_music.sh once first)
    bluetooth: bool = True
    airplay: bool = True
    airplay_bus: str = "session" # where shairport-sync's D-Bus interface lives; "session" for the user service install_music.sh sets up
    exclusive: bool = True       # a new source pauses the older one, so two phones don't play over each other
    initial_volume: float = 0.8  # each new music stream starts at this level (0-1); tuned for the small speaker, which is quieter than it sounds
    max_volume: float = 0.90     # the most Bob or the console may set (0-1). It does not limit the phone's own volume keys
    duck_level: float = 0.25     # while Bob speaks, the music falls to this fraction of its volume
    duck_hold_s: float = 0.8     # ...and returns this long after he finishes, so it doesn't bounce between sentences
    mic_deaf_while_playing: bool = True  # hands-free listening ignores the room while music plays (lyrics would be transcribed)
    poll_seconds: float = 1.0


@dataclass
class TimelineConfig:
    enabled: bool = False        # record what Bob saw, decided and did in logs/timeline (see manual 03, /timeline)
    thumbnails: bool = True      # keep small camera pictures too. They can show people
    thumb_every_s: float = 10.0  # at most one picture this often
    thumb_width: int = 320
    keep_days: float = 7.0       # older records are deleted
    max_mb: int = 200            # the folder never grows beyond this; the oldest files go first


@dataclass
class HomeConfig:
    enabled: bool = False        # let Bob turn the lights in his room on and off through Home Assistant (needs HA_TOKEN in .env)
    url: str = "http://homeassistant.local:8123"   # your Home Assistant, e.g. "http://192.168.1.20:8123"
    wifi: list = field(default_factory=list)       # Wi-Fi network names where Home Assistant exists, e.g. ["Adam's House"]. Empty = try everywhere
    rooms: list = field(default_factory=list)      # the Home Assistant areas Bob may control, e.g. ["Kitchen", "Living Room"]
    location_entity: str = ""    # a sensor whose state is the room Bob is in, e.g. "sensor.bob_area" (Bluetooth room tracking in HA)
    quiet_start: str = "22:00"   # between these times Bob may not turn lights ON (off is fine). Empty = no quiet hours
    quiet_end: str = "07:00"
    max_per_minute: int = 6      # most light changes Claude may make in a minute
    cooldown_s: float = 30.0     # least time between changes to the same room's lights, so he can't flicker them
    dark_below: float = 40.0     # camera brightness (0-255) under this counts as "dark"
    bright_above: float = 90.0   # ...and over this as "bright"; in between is "dim"
    # Room tags: printed AprilTags by each door that tell Bob which room he is in (see manual 19)
    tags: dict = field(default_factory=dict)   # tag number -> room, for example { 1 = "Kitchen", 2 = "Living Room" }
    tag_family: str = "tag36h11" # "tag36h11" (the standard AprilTag), "tag25h9" or "aruco4x4_50"
    tag_min_px: float = 40.0     # a tag must look at least this wide (pixels) to be believed: close to it, not seen through a door
    tag_valid_s: float = 300.0   # a sighting is trusted for this long
    tag_max_move_s: float = 20.0 # ...and until the wheels have run this many seconds since it (he can't feel leaving a room)
    tag_scan_hz: float = 3.0     # how often the camera is checked for tags
    tag_search_speed: float = 0.35   # /locate and find_my_room: how fast Bob turns on the spot looking for a tag
    tag_arrive_px: float = 180.0 # going to a room: he has arrived when its tag looks this wide in the picture (he is right at it)
    goto_speed: float = 0.35     # ...and how fast he approaches it (the speed cap still applies)
    goto_seconds: float = 90.0   # ...and how long he tries before giving up
    paths: dict = field(default_factory=dict)   # optional routes, room -> tag numbers to reach in order, e.g. { Kitchen = [5, 1] } (door tag 5, then the kitchen tag)
    tag_search_seconds: float = 25.0 # ...and how long he looks before giving up


@dataclass
class PowerConfig:
    enabled: bool = True         # people can power the Pi off with /shutdown (two steps; Claude cannot). Needs ./install_power.sh unless sudo is already open
    who: list = field(default_factory=lambda: ["owner", "operator"])   # which kinds of user: owner, operator (shared console), viewer (shared console), dashboard
    confirm_seconds: float = 30.0   # /shutdown confirm must follow within this time


@dataclass
class GamepadConfig:
    enabled: bool = False        # drive with an Xbox controller (see manual 22)
    device: str = "auto"         # "auto" finds /dev/input/js*; or a path such as "/dev/input/js1"
    deadzone: float = 0.15       # stick wobble below this is ignored
    slow_factor: float = 0.4     # speed while the slow button (LB) is held
    axis_turn: int = 0           # left stick left/right   (the numbers below are the Xbox layout of Linux's xpad driver)
    axis_throttle: int = 1       # left stick up/down
    btn_talk: int = 0            # A
    btn_estop: int = 1           # B
    btn_resume: int = 3          # Y
    btn_slow: int = 4            # LB
    btn_back: int = 6            # Back / View (hold to release the e-stop)
    btn_drive: int = 7           # Start / Menu


@dataclass
class RemoteConfig:
    enabled: bool = False        # a shared console: friends with a Pi login attach with `bob-console` (see manual 20)
    socket: str = "/tmp/bob-console.sock"
    operators: list = field(default_factory=lambda: ["bobops"])   # Linux groups whose members may run commands
    viewers: list = field(default_factory=lambda: ["bobview"])    # Linux groups that may only watch (and press the emergency stop)
    deny: list = field(default_factory=lambda: ["quit"])          # commands only the owner may run
    max_clients: int = 4


@dataclass
class IndexConfig:
    enabled: bool = True         # a searchable index of the timeline, notes, people, radio, warnings and manuals (/search)
    interval_s: float = 5.0      # how often it reads new records
    keep_days: float = 30.0      # radio and warning records older than this are dropped (the timeline has its own limit)
    log_warnings: bool = True    # include WARNING and ERROR lines from logs/bob.log
    manuals: bool = True         # include the manuals and README
    max_rows: int = 200000       # a safety net on the size of the index
    ai: bool = False             # let Claude search past timeline and radio records (the recall tool). Live: /index ai on


@dataclass
class BrainConfig:
    model: str = "claude-opus-5-5"
    effort: str = "low"          # low | medium | high - low keeps reactions snappy
    max_tokens: int = 16000
    tick_seconds: float = 2.0    # pause between autonomous ticks (in "change" mode: the least time between thoughts)
    think_when: str = "interval" # "interval" = think every tick_seconds; "change" = only when something changed (cheaper, manual 04)
    idle_max_s: float = 60.0     # "change" mode: think at least this often even if nothing happened
    change_percent: float = 4.0  # "change" mode: think when this % of the picture changed noticeably
    change_distance_cm: float = 15.0   # "change" mode: ...or when the distance sensor moved this far
    max_steps_per_tick: int = 8  # tool rounds per tick before forcing a new tick
    fallbacks: bool = True       # server-side refusal fallback
    start_paused: bool = False
    goal: str = (
        "Explore your surroundings carefully, avoid bumping into things, and be a "
        "friendly companion to any people you meet."
    )


@dataclass
class AlertsConfig:
    enabled: bool = False        # needs HEARTBEAT_URL and/or NOTIFY_URL in .env (manual 23)
    heartbeat_every_s: float = 60.0   # how often Bob pings the dead man's switch
    cooldown_s: float = 300.0    # least time between two notifications of the same kind
    notify: list = field(default_factory=lambda: ["restart", "estop", "camera", "power", "update", "vitals"])   # which events send a notification; also: start, stopped


@dataclass
class SleepConfig:
    enabled: bool = False        # follow the schedule below (/sleep on|off works either way)
    start: str = "23:00"         # asleep from...
    end: str = "07:00"           # ...until
    wake_for_s: float = 120.0    # someone speaking to him wakes him this long
    idle_max_s: float = 900.0    # asleep, he still takes a routine look this often
    change_percent: float = 15.0 # ...or when this % of the picture changes (a big change, not a passer-by)


@dataclass
class StartupConfig:
    stagger: bool = True         # start the heavy parts one at a time, waiting for the CPU to calm down, so boot doesn't overload the Pi
    calm_cpu_percent: float = 60.0   # a part starts once the CPU is below this busy for two checks in a row...
    max_wait_s: float = 25.0     # ...or after waiting this long
    step_pause_s: float = 2.0    # least pause between parts


@dataclass
class Config:
    drive: DriveConfig = field(default_factory=DriveConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    stream: StreamConfig = field(default_factory=StreamConfig)
    sensor: SensorConfig = field(default_factory=SensorConfig)
    follow: FollowConfig = field(default_factory=FollowConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    mic: MicConfig = field(default_factory=MicConfig)
    radio: RadioConfig = field(default_factory=RadioConfig)
    music: MusicConfig = field(default_factory=MusicConfig)
    timeline: TimelineConfig = field(default_factory=TimelineConfig)
    index: IndexConfig = field(default_factory=IndexConfig)
    home: HomeConfig = field(default_factory=HomeConfig)
    remote: RemoteConfig = field(default_factory=RemoteConfig)
    gamepad: GamepadConfig = field(default_factory=GamepadConfig)
    power: PowerConfig = field(default_factory=PowerConfig)
    startup: StartupConfig = field(default_factory=StartupConfig)
    alerts: AlertsConfig = field(default_factory=AlertsConfig)
    sleep: SleepConfig = field(default_factory=SleepConfig)
    brain: BrainConfig = field(default_factory=BrainConfig)


# Settings that only make sense with certain words. A typo here must stop Bob, not quietly pick another behaviour
# (for example "dcc" would otherwise be treated as servo mode and drive the wrong hardware).
CHOICES = {
    ("drive", "type"): ("dc", "servo"),
    ("drive", "pwm"): ("auto", "hardware", "pigpio", "software"),
    ("camera", "source"): ("auto", "csi", "usb"),
    ("audio", "tts"): ("piper", "espeak-ng"),
    ("audio", "player"): ("auto", "pw-play", "aplay"),
    ("mic", "mode"): ("hands-free", "handsfree", "auto", "push-to-talk", "ptt", "push"),
    ("mic", "wake_engine"): ("openwakeword", "text", "off"),
    ("radio", "role"): ("listen", "connect"),
    ("radio", "transport"): ("bluetooth", "wifi"),
    ("brain", "think_when"): ("interval", "change"),
    ("music", "airplay_bus"): ("session", "system"),
    ("home", "tag_family"): ("tag36h11", "tag25h9", "aruco4x4_50"),
    ("brain", "effort"): ("low", "medium", "high", "xhigh", "max"),
}


def load(path: Path) -> Config:
    """config.toml, then config.local.toml beside it (your own choices; not committed) on top."""
    cfg = Config()
    for source in (path, path.with_name("config.local.toml")):
        if source.exists():
            _apply(cfg, source)
    return cfg


def _apply(cfg: Config, path: Path) -> None:
    data = tomllib.loads(path.read_text())
    sections = {f.name for f in fields(cfg)}
    for name in data:
        if name not in sections:
            raise ValueError(f"{path}: unknown section [{name}] (known: {', '.join(sorted(sections))})")
    for section in fields(cfg):
        values = data.get(section.name, {})
        target = getattr(cfg, section.name)
        known = {f.name: f for f in fields(target)}
        for key, value in values.items():
            if key not in known:
                raise ValueError(f"{path}: unknown setting [{section.name}] {key}")
            default = getattr(target, key)
            if isinstance(default, float) and isinstance(value, int):
                value = float(value)
            if type(value) is not type(default):
                raise ValueError(f"{path}: [{section.name}] {key} should be {type(default).__name__}")
            allowed = CHOICES.get((section.name, key))
            if allowed and str(value).lower() not in allowed:
                raise ValueError(f"{path}: [{section.name}] {key} = {value!r} isn't one of: {', '.join(allowed)}")
            setattr(target, key, value)
