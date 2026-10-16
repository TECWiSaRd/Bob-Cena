"""Microphone input: hands-free or push-to-talk, transcribed on the Pi by faster-whisper.

The microphone is read with `arecord` (no extra audio libraries). Hands-free mode
cuts the stream into utterances by loudness; push-to-talk records between two
presses of Tab (or /talk). Each transcript is handed to `on_text`, which posts it to
Bob as if the operator had typed it.

Bob never hears himself: listening is paused while the speaker is playing and for
`after_speech_s` afterwards, and (optionally) while the wheels are turning.
"""
from __future__ import annotations

import array
import difflib
import importlib.util
import logging
import math
import queue
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

log = logging.getLogger("bob.mic")

RATE = 16000
CHUNK_MS = 30
CHUNK_BYTES = RATE * CHUNK_MS // 1000 * 2  # 16-bit mono
MODES = {"hands-free": "hands-free", "handsfree": "hands-free", "auto": "hands-free",
         "push-to-talk": "push-to-talk", "ptt": "push-to-talk", "push": "push-to-talk"}
# Whisper sometimes invents these from near-silence.
OWW_BYTES = 1280 * 2  # openWakeWord wants 80 ms frames of 16-bit audio
FILLER = {"hey", "hi", "okay", "ok", "hello", "yo"}
HALLUCINATIONS = {"", "you", "thanks for watching", "thank you for watching", "bye"}


def rms(data: bytes) -> float:
    """Loudness of a 16-bit chunk, 0.0-1.0."""
    samples = array.array("h")
    samples.frombytes(data[: len(data) // 2 * 2])
    if not samples:
        return 0.0
    return math.sqrt(sum(x * x for x in samples) / len(samples)) / 32768


def oww_usable() -> bool:
    """openWakeWord is installed and new enough (0.5+). Version 0.4 and earlier have a different interface
    and no model downloader; pip falls back to one of those when the newer ones can't install."""
    if importlib.util.find_spec("openwakeword") is None:
        return False
    try:
        from importlib.metadata import version
        major, minor = (int(x) for x in version("openwakeword").split(".")[:2])
        return (major, minor) >= (0, 5)
    except Exception:
        return True   # can't tell; assume it's fine


def _norm(token: str) -> str:
    return re.sub(r"[^\w']", "", token.lower())


def _similar(a: str, b: str) -> bool:
    # tolerates "bub" or "bop" for "bob" (Whisper mishearings), but not "rob" (different first sound) or "bobby"
    return (bool(a) and a[0] == b[0] and abs(len(a) - len(b)) <= 1
            and difflib.SequenceMatcher(None, a, b).ratio() >= 0.66)


def wake_words_from(model: str) -> list[str]:
    """'hey_jarvis' -> ['hey', 'jarvis'];  'wakewords/hey_bob.onnx' -> ['hey', 'bob']."""
    stem = re.sub(r"\.(onnx|tflite)$", "", model.split("/")[-1])
    stem = re.sub(r"_v?\d+(\.\d+)*$", "", stem)  # drop a version suffix such as _v0.1
    return [w for w in re.split(r"[_\s-]+", stem.lower()) if w]


def has_word(text: str, word: str, within: int = 4) -> bool:
    """Is `word` (loosely matched) among the first few words of the transcript?"""
    return any(_similar(_norm(t), word) for t in text.split()[:within])


def strip_wake(text: str, words: list[str]) -> tuple[str, bool]:
    """Remove a leading wake phrase from a transcript. Returns (rest, found).

    Each phrase word is optional and matched loosely, since Whisper often drops "hey" or
    mishears a name."""
    tokens = text.split()
    i, found = 0, False
    for word in words:
        while i < len(tokens) and _norm(tokens[i]) in FILLER and word not in FILLER:
            i += 1  # "okay, hey bob": skip stray greeting words
        if i < len(tokens) and _similar(_norm(tokens[i]), word):
            i += 1
            found = True
    return " ".join(tokens[i:]).lstrip(" ,.!?:;-").strip(), found


class Segmenter:
    """Cuts a stream of 30 ms chunks into utterances using loudness."""

    def __init__(self, threshold: float, silence_ms: int, max_s: float,
                 min_s: float = 0.4, start_chunks: int = 3, preroll_chunks: int = 10):
        self.threshold, self.silence_ms, self.max_s, self.min_s = threshold, silence_ms, max_s, min_s
        self.start_chunks = start_chunks
        self.preroll: deque[bytes] = deque(maxlen=preroll_chunks)  # keeps the quiet start of a word
        self.reset()

    def reset(self) -> None:
        self.preroll.clear()
        self.buf: list[bytes] = []
        self.active = False
        self.loud_run = 0
        self.quiet = 0

    def feed(self, data: bytes, level: float) -> bytes | None:
        loud = level > self.threshold
        if not self.active:
            self.preroll.append(data)
            self.loud_run = self.loud_run + 1 if loud else 0
            if self.loud_run >= self.start_chunks:
                self.active, self.buf, self.quiet = True, list(self.preroll), 0
            return None
        self.buf.append(data)
        self.quiet = 0 if loud else self.quiet + 1
        n = len(self.buf)
        if self.quiet * CHUNK_MS >= self.silence_ms or n * CHUNK_MS >= self.max_s * 1000:
            spoken_ms = (n - self.quiet) * CHUNK_MS
            audio = b"".join(self.buf)
            self.reset()
            return audio if spoken_ms >= self.min_s * 1000 else None
        return None


class Listener(threading.Thread):
    def __init__(self, cfg, on_text, audio, drive):
        super().__init__(name="mic", daemon=True)
        self.cfg, self.on_text, self.audio, self.drive = cfg, on_text, audio, drive
        self.mode = MODES.get(cfg.mode.lower(), "hands-free")
        self.threshold = cfg.threshold
        self.on = False
        self.state = "off"
        self.level = 0.0
        self._ptt = threading.Event()
        self._wake = threading.Event()
        self._quit = threading.Event()
        self._proc = None
        self._model = None
        self._failures = 0
        self._want_on = cfg.enabled
        self.wake_engine = cfg.wake_engine.lower()
        self.wake_threshold = cfg.wake_threshold
        self.on_wake = None            # called when someone says just the wake word (Bob chirps)
        self.music_busy = lambda: False  # set by the controller: True while music is playing
        self._awake_until = 0.0
        self._confirm_pending = False   # the audio model fired; the transcript must still contain the name
        self._oww = None
        self._oww_name = ""
        self._jobs: queue.Queue = queue.Queue(maxsize=3)   # utterances waiting for Whisper
        self._busy = False

    # ---- operator controls (called from the console thread) -----------------
    def problem(self) -> str | None:
        """Why listening can't work here, or None."""
        if importlib.util.find_spec("faster_whisper") is None:
            return "faster-whisper isn't installed: .venv/bin/pip install faster-whisper"
        if shutil.which("arecord") is None:
            return "arecord not found: sudo apt-get install alsa-utils"
        return None

    def set_enabled(self, on: bool) -> str:
        if on:
            if (why := self.problem()):
                return why
            self._failures = 0
        self.on = on
        if not on:
            self._ptt.clear()
            self._stop_proc()
            self.state = "off"
        self._wake.set()
        if not on:
            return "microphone off"
        return ("microphone on (hands-free: just talk)" if self.mode == "hands-free"
                else "microphone on (push-to-talk: press Tab or /talk to start and stop)")

    def set_mode(self, name: str) -> str:
        mode = MODES.get(name.lower())
        if mode is None:
            return "mode must be hands-free or push-to-talk (ptt)"
        self.mode = mode
        self._ptt.clear()
        self._stop_proc()
        self._wake.set()
        return f"mic mode: {mode}"

    def ptt_toggle(self) -> str:
        if not self.on:
            return "microphone is off - /listen on"
        if self.mode != "push-to-talk":
            return "hands-free mode is on; switch with /listen mode ptt"
        if self._ptt.is_set():
            self._ptt.clear()
            return "sending..."
        self._ptt.set()
        self._wake.set()
        return "recording - press Tab (or /talk) again when you're done"

    def describe(self) -> str:
        if not self.on:
            return "off"
        if self._busy:
            return f"{'PTT' if self.mode == 'push-to-talk' else 'hands-free'} (transcribing)"
        return f"{'PTT' if self.mode == 'push-to-talk' else 'hands-free'} ({self.state})"

    def wake_status(self) -> str:
        eng = self._engine()
        what = {"openwakeword": f"openWakeWord '{self.cfg.wake_model}' (threshold {self.wake_threshold:.2f})",
                "text": f"the word '{self.cfg.wake_word}' in the transcript",
                "off": "off: Bob reacts to everything he hears"}[eng]
        note = f" [{self.wake_engine} not available, using {eng}]" if eng != self.wake_engine else ""
        left = max(0, self._awake_until - time.monotonic())
        return f"wake word: {what}{note}; " + (f"awake for {left:.0f}s more" if left else "asleep") + \
               f". Window {self.cfg.wake_window_s:g}s. /listen wake off|oww|text|sleep, /listen wake threshold X|window N"

    def set_wake(self, arg: str) -> str:
        words = arg.lower().split()
        if not words:
            return self.wake_status()
        if words[0] == "threshold" and len(words) == 2:
            self.wake_threshold = max(0.05, min(0.99, float(words[1])))
            return f"wake word threshold {self.wake_threshold:.2f}"
        if words[0] == "window" and len(words) == 2:
            self.cfg.wake_window_s = max(1.0, min(120.0, float(words[1])))
            self._awake_until = 0.0   # close the current window so the new length is tested from a clean start
            return f"after waking, Bob listens for {self.cfg.wake_window_s:g}s without the wake word (asleep now)"
        if words[0] == "sleep":
            self._awake_until = 0.0
            self._confirm_pending = False
            return "asleep: say the wake word again"
        names = {"off": "off", "text": "text", "oww": "openwakeword", "openwakeword": "openwakeword"}
        if words[0] in names:
            self.wake_engine = names[words[0]]
            self._awake_until = 0.0
            self._stop_proc()  # restart the capture session with the new setting
            return self.wake_status()
        return "usage: /listen wake | off | oww | text | sleep | threshold X | window N"

    def status(self) -> str:
        return (f"mic {self.describe()}, level {self.level:.3f}, threshold {self.threshold:.3f}, "
                f"model {self.cfg.model}  (/listen on|off, /listen mode ptt|hands-free, "
                f"/listen threshold X, /talk)")

    def _engine(self) -> str:
        """The wake engine actually in use (openWakeWord falls back to text matching if not installed)."""
        if self.wake_engine == "openwakeword" and not oww_usable():
            if not getattr(self, "_warned_oww", False):
                self._warned_oww = True
                log.warning("openWakeWord is missing or too old (need 0.5+): listening for the word '%s' in the "
                            "transcript instead. Fix: .venv/bin/pip install --no-deps --upgrade 'openwakeword>=0.6'",
                            self.cfg.wake_word)
            return "text"
        return self.wake_engine

    def _awake(self) -> bool:
        return time.monotonic() < self._awake_until

    def _open_window(self) -> None:
        self._awake_until = time.monotonic() + self.cfg.wake_window_s

    def stop(self) -> None:
        self._quit.set()
        self.on = False
        self._stop_proc()
        self._wake.set()

    # ---- capture ---------------------------------------------------------
    def _stop_proc(self) -> None:
        proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()  # unblocks a read in the listener thread

    def _open(self):
        cmd = ["arecord", "-q", "-t", "raw", "-f", "S16_LE", "-r", str(RATE), "-c", "1"]
        if self.cfg.device:
            cmd += ["-D", self.cfg.device]
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def _deaf(self) -> bool:
        if self.music_busy():   # lyrics would be transcribed (and could even contain the wake word)
            return True
        if self.audio.active or time.monotonic() - self.audio.last_end < self.cfg.after_speech_s:
            return True
        return bool(self.cfg.pause_while_driving and self.drive.moving)

    def _read(self, proc) -> bytes | None:
        data = proc.stdout.read(CHUNK_BYTES)
        if len(data) < CHUNK_BYTES:
            return None
        return data

    def _load_oww(self):
        model = self.cfg.wake_model
        local = Path(__file__).resolve().parent / model
        if model.endswith((".onnx", ".tflite")) and not Path(model).is_absolute() and local.exists():
            model = str(local)  # "wakewords/hey_bob.onnx" is relative to the Bob folder, wherever Bob was started from
        if self._oww is None or self._oww_name != model:
            from openwakeword.model import Model
            framework = "tflite" if model.endswith(".tflite") else "onnx"
            kwargs = {}
            verifier = self.cfg.wake_verifier
            if verifier:
                vpath = Path(verifier) if Path(verifier).is_absolute() else Path(__file__).resolve().parent / verifier
                if vpath.exists():
                    # The verifier is a pickle file: loading one runs code, so only use a file you trained yourself.
                    key = Path(model).stem if "/" in model or model.endswith((".onnx", ".tflite")) else model
                    kwargs = {"custom_verifier_models": {key: str(vpath)},
                              "custom_verifier_threshold": min(0.3, self.wake_threshold)}
                    log.info("Wake word verifier loaded: %s", vpath.name)
                else:
                    log.warning("wake_verifier %s not found - continuing without it", verifier)
            try:
                self._oww = Model(wakeword_models=[model], inference_framework=framework, **kwargs)
            except Exception:
                import openwakeword
                log.info("Downloading wake word models (one time)...")
                openwakeword.utils.download_models()
                self._oww = Model(wakeword_models=[model], inference_framework=framework, **kwargs)
            self._oww_name = model
            log.info("Wake word ready: say '%s'", " ".join(wake_words_from(model)))
        return self._oww

    def _oww_hit(self, oww, frame: bytes) -> bool:
        import numpy as np
        scores = oww.predict(np.frombuffer(frame, dtype=np.int16))
        return bool(scores) and max(scores.values()) >= self.wake_threshold

    def _enqueue(self, pcm: bytes, ptt: bool) -> None:
        try:
            self._jobs.put_nowait((pcm, ptt))
        except queue.Full:
            log.warning("Still busy transcribing; dropped what you just said")

    def _hands_free(self, proc) -> None:
        """Capture until the session changes. Utterances are handed to the transcriber thread, so
        the microphone keeps listening while Whisper works."""
        seg = Segmenter(self.threshold, self.cfg.silence_ms, self.cfg.max_seconds)
        engine = self._engine()
        oww = self._load_oww() if engine == "openwakeword" else None
        pending = b""
        while self.on and self.mode == "hands-free" and not self._quit.is_set() and engine == self._engine():
            data = self._read(proc)
            if data is None:
                return
            self.level = rms(data)
            if self._deaf():
                seg.reset()
                pending = b""
                if oww:
                    oww.reset()
                self.state = "paused"
                continue
            seg.threshold = self.threshold  # /listen threshold applies live
            utterance = seg.feed(data, self.level)
            if oww:
                pending += data
                while len(pending) >= OWW_BYTES:
                    frame, pending = pending[:OWW_BYTES], pending[OWW_BYTES:]
                    if self._oww_hit(oww, frame):
                        if not self._awake():
                            log.info("WAKE heard '%s'", " ".join(wake_words_from(self.cfg.wake_model)))
                            self._confirm_pending = self.cfg.wake_confirm
                        self._open_window()
                        oww.reset()
            self.state = "listening" if (engine != "openwakeword" or self._awake()) else "waiting for wake word"
            if utterance is None:
                continue
            if engine == "openwakeword":
                if not self._awake():
                    continue  # nobody said the wake word: don't spend CPU on Whisper
            self._enqueue(utterance, False)  # if it was only the wake word, _gate() chirps instead of delivering

    def _worker(self) -> None:
        while not self._quit.is_set():
            try:
                pcm, ptt = self._jobs.get(timeout=0.5)
            except queue.Empty:
                continue
            self._busy = True
            try:
                text = self._gate(self._transcribe(pcm), ptt)
                if text:
                    self.on_text(text, ptt)
            except Exception as e:
                log.error("Transcription problem: %s", e)
            finally:
                self._busy = False

    def _gate(self, text: str, ptt: bool) -> str:
        """Apply the wake word to a transcript. Returns what to deliver ('' = nothing)."""
        engine = self._engine()
        if ptt or engine == "off" or not text:
            return text
        if engine == "openwakeword":
            words = wake_words_from(self.cfg.wake_model)
            rest, _ = strip_wake(text, words)
            if self._confirm_pending:
                if not has_word(text, words[-1]):
                    log.info("WAKE ignored: the audio model fired but I heard %r, not '%s'", text[:60], words[-1])
                    self._awake_until = 0.0
                    self._confirm_pending = False
                    return ""
                self._confirm_pending = False
        else:
            rest, found = strip_wake(text, [self.cfg.wake_word])
            if found:
                if not self._awake():
                    log.info("WAKE heard '%s'", self.cfg.wake_word)
                self._open_window()
            elif not self._awake():
                return ""  # not addressed to Bob
        if not rest:  # only the wake word: acknowledge and wait for the command
            if self.on_wake:
                self.on_wake()
            return ""
        self._open_window()  # a delivered command keeps the conversation open
        return rest

    def _push_to_talk(self, proc) -> bytes | None:
        chunks: list[bytes] = []
        limit = int(self.cfg.max_seconds * 1000 / CHUNK_MS)
        self.state = "recording"
        while self._ptt.is_set() and self.on and self.mode == "push-to-talk" and len(chunks) < limit:
            data = self._read(proc)
            if data is None:
                break
            self.level = rms(data)
            chunks.append(data)
        self._ptt.clear()
        return b"".join(chunks) if len(chunks) * CHUNK_MS >= 300 else None

    def run(self) -> None:
        threading.Thread(target=self._worker, name="mic-transcriber", daemon=True).start()
        if self._want_on:
            log.info("%s", self.set_enabled(True))
        while not self._quit.is_set():
            if not self.on or (self.mode == "push-to-talk" and not self._ptt.is_set()):
                self.state = "ready" if self.on else "off"
                self._wake.wait(0.5)
                self._wake.clear()
                continue
            try:
                proc = self._proc = self._open()
                try:
                    ptt = self.mode == "push-to-talk"
                    pcm = self._push_to_talk(proc) if ptt else self._hands_free(proc)
                finally:
                    self._stop_proc()
                    try:
                        proc.wait(2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    err = ""
                    if proc.returncode not in (0, -15):  # -15 = we stopped it ourselves
                        err = proc.stderr.read().decode(errors="replace").strip()
                    proc.stderr.close()
                    proc.stdout.close()
                if err:
                    raise RuntimeError(err.splitlines()[-1])
                self._failures = 0
                if pcm:
                    self._enqueue(pcm, ptt)
            except Exception as e:
                self._failures += 1
                log.error("Microphone problem: %s", e)
                if self._failures >= 3:
                    log.error("Giving up on the microphone - fix it, then /listen on")
                    self.on = False
                    self.state = "off"
                else:
                    time.sleep(2)

    # ---- speech to text ----------------------------------------------------
    def _load_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            log.info("Loading speech model %s (the first run downloads it)...", self.cfg.model)
            self._model = WhisperModel(self.cfg.model, device="cpu", compute_type="int8",
                                       cpu_threads=self.cfg.cpu_threads)
            log.info("Speech model ready")
        return self._model

    def _transcribe(self, pcm: bytes) -> str:
        import numpy as np

        model = self._load_model()
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = model.transcribe(
            audio, language=self.cfg.language or None, beam_size=1,
            vad_filter=True, condition_on_previous_text=False)
        parts = [s.text.strip() for s in segments
                 if not (s.no_speech_prob > 0.6 and s.avg_logprob < -0.8)]
        text = " ".join(p for p in parts if p).strip()
        return "" if text.lower().strip(" .!?,") in HALLUCINATIONS else text
