"""Recognising people Bob has been introduced to, on the Pi, with their consent.

The rules this follows:
  * Bob learns a face only when a person with permission asks (`/face remember NAME`, then `/face remember confirm`).
    He never enrols anyone by himself, and a face he doesn't know is never stored.
  * Only numbers are kept (an "embedding" of 128 values per sample), never a photo. They live in faces.json on the Pi,
    readable by Bob's account only, and are never sent to Claude. Claude is only told a NAME when a stored face matches.
  * It gets better only when a person confirms (`/face improve NAME` while that person is in front of him), and it
    stays small: a handful of samples per person.
  * `/face forget NAME` and `/face forget all` erase them. The feature is off until it is switched on in config.

Matching is a guess by a small neural network (OpenCV's SFace). It can be wrong, more so in poor light, at an angle,
or between similar-looking faces, so Bob is told to treat a name as likely and never as certain.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger("bob.faces")

YUNET_FILE = "face_detection_yunet_2023mar.onnx"
SFACE_FILE = "face_recognition_sface_2021dec.onnx"
NAME_OK = re.compile(r"[^\w '\-]", re.UNICODE)


def clean_name(text: str) -> str:
    """A person's name as it will be shown to Claude: letters, digits, spaces, hyphens and apostrophes only, one line."""
    return " ".join(NAME_OK.sub(" ", str(text)).split())[:30]


def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


class FaceBook:
    """Who Bob has been introduced to: name -> a few embeddings. A small JSON file, written atomically, mode 0600."""

    def __init__(self, path: Path, max_people: int = 20, max_samples: int = 8):
        self.path, self.max_people, self.max_samples = Path(path), max_people, max_samples
        self.people: dict[str, dict] = {}
        self._lock = threading.RLock()
        try:
            data = json.loads(self.path.read_text()) if self.path.exists() else {}
            for name, entry in (data if isinstance(data, dict) else {}).items():
                samples = [s for s in entry.get("samples", []) if isinstance(s, list) and s and all(isinstance(v, (int, float)) for v in s)]
                if samples:
                    self.people[str(name)] = {"samples": samples[-max_samples:], "added": str(entry.get("added", "")),
                                              "by": str(entry.get("by", ""))}
        except (ValueError, OSError, AttributeError):
            self.people = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".faces-")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(self.people, f)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def key(self, name: str) -> str | None:
        return next((k for k in self.people if k.lower() == name.strip().lower()), None)

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self.people)

    def count(self, name: str) -> int:
        with self._lock:
            key = self.key(name)
            return len(self.people[key]["samples"]) if key else 0

    def add(self, name: str, embeddings: list[list[float]], by: str | None) -> str:
        """Add samples for a person (a new person needs room). When full, each new sample replaces the stored one it
        most resembles, so what is kept stays varied (different light and angles)."""
        name = clean_name(name)
        if not name:
            raise ValueError("I need a name")
        with self._lock:
            key = self.key(name)
            if key is None:
                if len(self.people) >= self.max_people:
                    raise ValueError(f"I already know {self.max_people} people: /face forget someone first")
                key = name
                self.people[key] = {"samples": [], "added": datetime.now().strftime("%Y-%m-%d %H:%M"), "by": by or ""}
            samples = self.people[key]["samples"]
            for emb in embeddings:
                emb = [float(v) for v in emb]
                if len(samples) < self.max_samples:
                    samples.append(emb)
                else:
                    samples[max(range(len(samples)), key=lambda i: cosine(samples[i], emb))] = emb
            self._save()
            return key

    def forget(self, name: str) -> bool:
        with self._lock:
            key = self.key(name)
            if key is None:
                return False
            del self.people[key]
            self._save()
            return True

    def forget_all(self) -> int:
        with self._lock:
            n = len(self.people)
            self.people = {}
            self._save()
            return n

    def match(self, emb, threshold: float, margin: float) -> tuple[str | None, float]:
        """(name, score) of the stored person this face most resembles, or (None, best score) when nobody is close
        enough or two people are too alike to say."""
        with self._lock:
            scores = sorted(((max(cosine(s, emb) for s in e["samples"]), n) for n, e in self.people.items()), reverse=True)
        if not scores:
            return None, 0.0
        best, name = scores[0]
        runner_up = scores[1][0] if len(scores) > 1 else -1.0
        if best < threshold or best - runner_up < margin:
            return None, best
        return name, best


class SFaceBackend:
    """Finds faces (YuNet) and turns each into an embedding (SFace), using OpenCV. Needs the two model files in models/."""

    def __init__(self, model_dir: Path):
        import cv2
        import numpy as np

        self.cv2, self.np = cv2, np
        yunet, sface = Path(model_dir) / YUNET_FILE, Path(model_dir) / SFACE_FILE
        missing = [p.name for p in (yunet, sface) if not p.exists() or p.stat().st_size < 100_000]
        if missing or not hasattr(cv2, "FaceRecognizerSF"):
            raise RuntimeError("face recognition needs OpenCV's FaceRecognizerSF and the model files "
                               f"{', '.join(missing) or YUNET_FILE + ', ' + SFACE_FILE} in models/ (run install.sh)")
        self._det = cv2.FaceDetectorYN.create(str(yunet), "", (640, 480), 0.8, 0.3, 5)
        self._rec = cv2.FaceRecognizerSF.create(str(sface), "")

    def faces_in(self, bgr):
        """[(box as fractions (x, y, w, h), unit-length embedding as a list)] for each face found."""
        cv2, np = self.cv2, self.np
        h0, w0 = bgr.shape[:2]
        width = 640
        height = max(1, int(h0 * width / w0))
        small = cv2.resize(bgr, (width, height))
        self._det.setInputSize((width, height))
        _, rows = self._det.detect(small)
        out = []
        for row in (rows if rows is not None else []):
            crop = self._rec.alignCrop(small, row)
            feat = self._rec.feature(crop).flatten().astype("float64")
            norm = float(np.linalg.norm(feat))
            if norm == 0:
                continue
            x, y, w, h = (float(v) for v in row[:4])
            out.append(((x / width, y / height, w / width, h / height), (feat / norm).tolist()))
        return out


class Seen:
    def __init__(self, name, score, box, embedding):
        self.name, self.score, self.box, self.embedding = name, score, box, embedding


class FaceService:
    """Ties it together: look at a picture, say who is in it, enrol on request, improve on confirmation."""

    FRESH_S = 12.0           # a sighting this recent may be mentioned to Claude
    IMPROVE_WINDOW_S = 30.0  # /face improve uses a face seen this recently

    def __init__(self, cfg, book: FaceBook, backend_factory, clock=time.monotonic, sleep=time.sleep):
        self.cfg, self.book, self._factory = cfg, book, backend_factory
        self._clock, self._sleep = clock, sleep
        self.enabled = bool(cfg.enabled)
        self._backend = None
        self.problem: str | None = None
        self._last: tuple[float, list[Seen]] | None = None      # kept in memory only, never written anywhere
        self._pending: dict[str, tuple[float, str]] = {}        # who asked -> (deadline, name) for /face remember
        self._lock = threading.RLock()

    # ---- the backend is built on first use, so a Pi without the models still runs Bob ------------------------------
    def backend(self):
        if self._backend is None and self.problem is None:
            try:
                self._backend = self._factory()
            except Exception as e:
                self.problem = str(e)
                log.warning("Face recognition unavailable: %s", e)
        return self._backend

    @property
    def available(self) -> bool:
        return self.backend() is not None

    # ---- looking -----------------------------------------------------------------------------------------------------
    def look(self, bgr) -> list[Seen]:
        backend = self.backend()
        if not self.enabled or backend is None or bgr is None:
            return []
        seen = []
        for box, emb in backend.faces_in(bgr):
            name, score = self.book.match(emb, self.cfg.match_threshold, self.cfg.margin)
            seen.append(Seen(name, score, box, emb))
        with self._lock:
            self._last = (self._clock(), seen)
        return seen

    def look_jpeg(self, jpeg: bytes) -> list[Seen]:
        if not self.enabled or not jpeg or not self.book.people:
            return []          # nobody is enrolled, so there is nothing to recognise (and no work to do)
        try:
            import cv2
            import numpy as np
            bgr = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        except Exception as e:
            log.debug("could not decode the picture for faces: %s", e)
            return []
        return self.look(bgr)

    def status_line(self) -> str:
        """For Claude's status report: names only, and only for a recent sighting."""
        with self._lock:
            last = self._last
        if not self.enabled or last is None or self._clock() - last[0] > self.FRESH_S:
            return ""
        names = sorted({s.name for s in last[1] if s.name})
        unknown = sum(1 for s in last[1] if not s.name)
        if not names:
            return ""
        text = "People I recognise in view (a guess, can be wrong): " + ", ".join(names) + "."
        if unknown:
            text += f" {unknown} other face{'s' * (unknown != 1)} I don't recognise."
        return text

    # ---- enrolling: only on request, with a second confirming step ------------------------------------------------
    def request_remember(self, who: str, name: str) -> str:
        name = clean_name(name)
        if not name:
            return "usage: /face remember <name>"
        if not self.available:
            return f"can't do that: {self.problem}"
        if self.book.key(name) is None and len(self.book.people) >= self.book.max_people:
            return f"I already know {self.book.max_people} people: /face forget someone first"
        with self._lock:
            self._pending[who] = (self._clock() + self.cfg.confirm_seconds, name)
        return (f"Only do this if {name} agrees. I will take {self.cfg.samples_to_take} pictures over a few seconds of the ONE face I "
                f"can see, keep only numbers describing it (no photo), and recognise it later. {name} must be the only person in "
                f"front of me, facing me. Type /face remember confirm within {self.cfg.confirm_seconds:g} seconds "
                f"(/face remember cancel to stop). /face forget {name} erases it any time.")

    def confirm_remember(self, who: str, grab, by: str | None = None) -> str:
        with self._lock:
            pending = self._pending.pop(who, None)
        if pending is None or self._clock() > pending[0]:
            return "type /face remember <name> first, then /face remember confirm"
        name = pending[1]
        backend = self.backend()
        if backend is None:
            return f"can't do that: {self.problem}"
        samples: list[list[float]] = []
        crowded = 0
        for i in range(max(1, self.cfg.samples_to_take) * 3):         # up to three tries per sample
            if len(samples) >= self.cfg.samples_to_take:
                break
            frame = grab()
            faces = backend.faces_in(frame) if frame is not None else []
            if len(faces) == 1:
                samples.append(faces[0][1])
            elif len(faces) > 1:
                crowded += 1
            self._sleep(self.cfg.sample_gap_s)
        if len(samples) < min(3, self.cfg.samples_to_take):
            why = "I could see more than one face" if crowded else "I couldn't see a face clearly"
            return f"Nothing was saved. {why}: stand alone, face the camera, in good light, and try again."
        try:
            key = self.book.add(name, samples, by)
        except (ValueError, OSError) as e:
            return f"Nothing was saved: {e}"
        with self._lock:
            self._last = None
        return f"OK, I will recognise {key} now ({self.book.count(key)} samples stored, numbers only)."

    def cancel_remember(self, who: str) -> str:
        with self._lock:
            had = self._pending.pop(who, None) is not None
        return "cancelled" if had else "nothing to cancel"

    # ---- improving: only when a person says who it is ----------------------------------------------------------------
    def improve(self, name: str, by: str | None = None) -> str:
        key = self.book.key(name)
        if key is None:
            return f"I don't know a {name.strip()}: /face remember {name.strip()} first"
        with self._lock:
            last = self._last
        if last is None or self._clock() - last[0] > self.IMPROVE_WINDOW_S:
            return "I haven't looked at anyone in the last 30 seconds. Stand in front of me, wait a moment, then try again."
        faces = last[1]
        if len(faces) != 1:
            return "I need to see exactly one face to learn from it" + (f" (I see {len(faces)})." if faces else ".")
        try:
            self.book.add(key, [faces[0].embedding], by)
        except (ValueError, OSError) as e:
            return f"Nothing was saved: {e}"
        return f"Thanks, I'll recognise {key} a little better ({self.book.count(key)} samples)."

    # ---- housekeeping ---------------------------------------------------------------------------------------------------
    def forget(self, name: str) -> str:
        done = self.book.forget(name)
        with self._lock:
            self._last = None
        return f"forgot {name.strip()}" if done else f"I don't know a {name.strip()}"

    def forget_all(self) -> str:
        n = self.book.forget_all()
        with self._lock:
            self._last = None
        return f"forgot everyone ({n})"

    def describe(self) -> str:
        if not self.enabled:
            return "face recognition is off ([faces] enabled in config.local.toml turns it on)"
        if not self.available:
            return f"face recognition is on but unavailable: {self.problem}"
        names = [f"{n} ({self.book.count(n)})" for n in self.book.names()]
        return "face recognition is on. Known: " + (", ".join(names) if names else "nobody yet (/face remember <name>)")
