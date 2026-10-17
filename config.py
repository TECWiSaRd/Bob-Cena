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
    fov_deg: float = 62.0        # horizontal field of view: Pi Camera v2 ~62, Camera Module 3 ~66, most webcams 60-78


@dataclass
class StreamConfig:
    enabled: bool = True
    host: str = "0.0.0.0"        # use "127.0.0.1" to keep it local (e.g. behind an SSH tunnel)
    port: int = 8080
    fps: float = 10.0
    dashboard: bool = True       # phone control page at /dash; only active when BOB_STREAM_TOKEN is set


@dataclass
class SensorConfig:
    enabled: bool = False        # HC-SR04 ultrasonic sensor facing forward (see sensors.py for wiring)
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
    peer_address: str = ""       # the other robot's Bluetooth address, needed for role = "connect"
    channel: int = 3             # RFCOMM channel (1-30); both robots must use the same one
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
class BrainConfig:
    model: str = "claude-opus-5-5"
    effort: str = "low"          # low | medium | high - low keeps reactions snappy
    max_tokens: int = 16000
    tick_seconds: float = 2.0    # pause between autonomous ticks
    max_steps_per_tick: int = 8  # tool rounds per tick before forcing a new tick
    fallbacks: bool = True       # server-side refusal fallback
    start_paused: bool = False
    goal: str = (
        "Explore your surroundings carefully, avoid bumping into things, and be a "
        "friendly companion to any people you meet."
    )


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
    ("music", "airplay_bus"): ("session", "system"),
    ("brain", "effort"): ("low", "medium", "high", "xhigh", "max"),
}


def load(path: Path) -> Config:
    cfg = Config()
    if not path.exists():
        return cfg
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
    return cfg
