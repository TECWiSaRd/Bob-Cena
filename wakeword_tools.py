#!/usr/bin/env python3
"""Make Bob's "hey bob" wake word fit YOUR voice and room.

    python wakeword_tools.py record  [--device plughw:1,0]   record your own voice saying (and not saying) "hey bob"
    python wakeword_tools.py train                           train a small voice-specific "verifier" from those clips
    python wakeword_tools.py score FILE.wav ...              show what the wake word model (and verifier) make of clips

`record` + `score` are the useful part: they let you measure any wake word model on YOUR voice in YOUR room,
which is the honest way to compare models. `train` is EXPERIMENTAL. A verifier is a tiny extra classifier on
top of the model ("does this sound like the same person saying the real phrase?"). In my test, with 6 positive
and 9 negative computer-voice clips, it lowered scores modestly but did not separate "Hey Bob" from look-alikes
such as "Hey Boss", so retraining the model itself (see TRAINING_HEY_BOB.md) is the better fix. Real recordings
may do better; measure with `score` before trusting it. Clips go in wakeword_clips/, the result in
wakewords/<name>_verifier.pkl.

SAFETY: a verifier is a Python "pickle", and loading a pickle runs code. Only ever use a verifier you
trained yourself on this machine. Never download one.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import wave
from pathlib import Path

import config

BASE = Path(__file__).resolve().parent
CLIPS = BASE / "wakeword_clips"

# What to say when recording. Negatives include look-alikes: they teach the verifier your "no".
POSITIVE_PROMPTS = ["Say: hey bob", "Say: hey bob (a bit quieter)", "Say: hey, bob!", "Say: hey bob (a bit faster)",
                    "Say: hey bob, as if calling across a room", "Say: hey bob (relaxed)"]
NEGATIVE_PROMPTS = ["Say: hey rob", "Say: hey bobby", "Say: hey boss", "Say: hey mom, what's for dinner",
                    "Say any normal sentence, e.g. 'the weather is nice today'", "Say a different sentence, about 6 seconds long",
                    "Chat normally for about 6 seconds", "Say: hey bud, hey bill, hey ben"]


def mic_cfg():
    return config.load(BASE / "config.toml").mic


def model_path(mic) -> Path:
    p = Path(mic.wake_model)
    p = p if p.is_absolute() else BASE / p
    if not p.exists():
        sys.exit(f"wake word model not found: {p}  (set wake_model in config.toml to your .onnx file)")
    return p


def record_one(path: Path, seconds: int, device: str) -> None:
    cmd = ["arecord", "-q", "-f", "S16_LE", "-r", "16000", "-c", "1", "-d", str(seconds)] + (["-D", device] if device else []) + [str(path)]
    subprocess.run(cmd, check=True)


def check_wav(path: Path) -> None:
    with wave.open(str(path)) as w:
        if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, 2, 16000):
            sys.exit(f"{path} must be 16 kHz, 16-bit, mono WAV (arecord -f S16_LE -r 16000 -c 1 makes that)")


def cmd_record(args) -> None:
    mic = mic_cfg()
    device = args.device or mic.device
    for kind, prompts, secs in (("positive", POSITIVE_PROMPTS, 3), ("negative", NEGATIVE_PROMPTS, 6)):
        (CLIPS / kind).mkdir(parents=True, exist_ok=True)
        print(f"\n=== {kind} clips ({secs} seconds each). Use your normal voice, at the distance Bob will hear you from.")
        for i, prompt in enumerate(prompts, 1):
            input(f"[{kind} {i}/{len(prompts)}] {prompt}   Press Enter, then speak after the beep... ")
            print("\a  recording...", flush=True)
            record_one(CLIPS / kind / f"{kind}_{i:02d}.wav", secs, device)
    print("\n=== room noise (6 seconds of silence, with the fan, TV or motors running as they would be)")
    input("Press Enter, then stay quiet... ")
    record_one(CLIPS / "negative" / "negative_noise.wav", 6, device)
    print(f"\nDone. Clips are in {CLIPS}. Next: python wakeword_tools.py train")


def cmd_train(args) -> None:
    import openwakeword
    mic = mic_cfg()
    model = model_path(mic)
    pos = sorted((CLIPS / "positive").glob("*.wav"))
    neg = sorted((CLIPS / "negative").glob("*.wav"))
    if len(pos) < 3 or len(neg) < 2:
        sys.exit(f"need at least 3 positive and 2 negative clips in {CLIPS} (run: record). Found {len(pos)} and {len(neg)}.")
    for p in pos + neg:
        check_wav(p)
    out = model.with_name(model.stem + "_verifier.pkl")
    openwakeword.train_custom_verifier(
        positive_reference_clips=[str(p) for p in pos], negative_reference_clips=[str(p) for p in neg],
        output_path=str(out), model_name=str(model), inference_framework="onnx" if model.suffix == ".onnx" else "tflite")
    print(f"\nSaved {out}\nNow set this in config.toml under [mic]:\n    wake_verifier = \"{out.relative_to(BASE)}\"")


def cmd_score(args) -> None:
    import numpy as np
    from openwakeword.model import Model
    mic = mic_cfg()
    model = model_path(mic)
    fw = "onnx" if model.suffix == ".onnx" else "tflite"
    plain = Model(wakeword_models=[str(model)], inference_framework=fw)
    name = next(iter(plain.models))
    verifier = model.with_name(model.stem + "_verifier.pkl")
    checked = (Model(wakeword_models=[str(model)], inference_framework=fw, custom_verifier_models={name: str(verifier)},
                     custom_verifier_threshold=0.3) if verifier.exists() else None)
    print(f"{'clip':40} {'model':>7}" + (f" {'+verifier':>10}" if checked else "") + f"    (wakes at {mic.wake_threshold})")
    for f in args.files:
        check_wav(Path(f))
        with wave.open(f) as w:
            audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        audio = np.concatenate([np.zeros(16000, np.int16), audio, np.zeros(16000, np.int16)])
        row = []
        for m in (plain, checked):
            if m is None:
                continue
            m.reset()
            row.append(max(m.predict(audio[i:i + 1280])[name] for i in range(0, len(audio) - 1279, 1280)))
        print(f"{Path(f).name[:40]:40} {row[0]:7.2f}" + (f" {row[1]:10.2f}" if checked else ""))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record"); r.add_argument("--device", default=""); r.set_defaults(fn=cmd_record)
    sub.add_parser("train").set_defaults(fn=cmd_train)
    s = sub.add_parser("score"); s.add_argument("files", nargs="+"); s.set_defaults(fn=cmd_score)
    a = ap.parse_args()
    a.fn(a)
