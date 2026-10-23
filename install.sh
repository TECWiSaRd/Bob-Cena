#!/usr/bin/env bash
# One-time setup on the Pi (Raspberry Pi OS Bookworm). Run from this folder:
#   ./install.sh            install deps + venv
#   ./install.sh --service  also start Bob automatically at boot (inside tmux)
set -euo pipefail
cd "$(dirname "$0")"
DIR="$(pwd)"

echo "== System packages"
sudo apt-get update
sudo apt-get install -y python3-venv python3-picamera2 python3-gpiozero \
    python3-opencv v4l-utils espeak-ng alsa-utils tmux openssl avahi-utils git
# Steady servo pulses: hardware PWM on GPIO12/13 (needs a one-time overlay + reboot).
# pigpio is only an optional fallback; newer Pi OS releases no longer ship it.
CONFIG_TXT=/boot/firmware/config.txt
OVERLAY="dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4"
if [ -f "$CONFIG_TXT" ] && ! grep -qF "$OVERLAY" "$CONFIG_TXT"; then
    echo "$OVERLAY" | sudo tee -a "$CONFIG_TXT" >/dev/null
    echo "!! Added hardware PWM overlay to $CONFIG_TXT - REBOOT before running Bob: sudo reboot"
fi
sudo apt-get install -y pigpio python3-pigpio 2>/dev/null \
    && sudo systemctl enable --now pigpiod || true

echo "== Python venv"
python3 -m venv --system-site-packages .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "== Speech recognition (faster-whisper, for the USB microphone)"
# Best effort: Bob works without it; /listen on will say what is missing.
if .venv/bin/pip install faster-whisper \
   && .venv/bin/python -c "from faster_whisper import WhisperModel; WhisperModel('tiny.en', device='cpu', compute_type='int8')"; then
    echo "faster-whisper ready (tiny.en model downloaded)"
else
    echo "!! faster-whisper install failed - the microphone feature will be unavailable"
fi

echo "== Wake word (openWakeWord)"
# openWakeWord 0.5+ asks for tflite-runtime on Linux, which has no build for newer Python. If we let pip resolve
# it, pip quietly installs an ancient 0.4.0 instead (wrong interface, no model downloader). So install its other
# requirements, then openWakeWord itself with --no-deps (Bob uses the ONNX models, which need no tflite).
if .venv/bin/pip install onnxruntime scipy scikit-learn tqdm requests \
   && .venv/bin/pip install --no-deps --upgrade "openwakeword>=0.6" \
   && .venv/bin/python -c "import openwakeword; openwakeword.utils.download_models(model_names=['hey_jarvis'])"; then
    echo "openWakeWord $(.venv/bin/pip show openwakeword | grep Version) ready ('hey jarvis')"
else
    echo "!! openWakeWord install failed - Bob will listen for the word 'bob' in the transcript instead"
fi

echo "== Face detector (person following)"
mkdir -p models
YUNET=models/face_detection_yunet_2023mar.onnx
YUNET_SHA=8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4
if [ ! -f "$YUNET" ]; then
    # raw.githubusercontent.com serves only a Git LFS pointer for this file; the media host serves the real model
    if curl -fsSL -o "$YUNET.tmp" "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx" \
       && echo "$YUNET_SHA  $YUNET.tmp" | sha256sum -c --quiet -; then
        mv "$YUNET.tmp" "$YUNET" && echo "YuNet face model ready"
    else
        rm -f "$YUNET.tmp"
        echo "!! face model download failed - following will use OpenCV's older built-in detector"
    fi
fi

echo "== Piper (offline natural voice)"
# Best effort: if this fails Bob speaks with espeak-ng instead.
if .venv/bin/pip install piper-tts \
   && .venv/bin/python -m piper.download_voices --data-dir voices en_US-lessac-medium; then
    echo "Piper ready (voice in $DIR/voices)"
else
    echo "!! Piper install failed - Bob will use espeak-ng for speech"
fi

if [ ! -f .env ]; then
    cp .env.example .env
    echo "!! Put your Claude API key in $DIR/.env"
fi
chmod 600 .env

if [ "${1:-}" = "--service" ]; then
    echo "== systemd service"
    sed -e "s|@USER@|$USER|g" -e "s|@DIR@|$DIR|g" -e "s|@UID@|$(id -u)|g" bob.service | sudo tee /etc/systemd/system/bob.service >/dev/null
    sudo systemctl daemon-reload
    sudo systemctl enable bob
    echo "Bob will start at boot. Start now: sudo systemctl start bob"
    echo "Open his console:  tmux attach -t bob   (detach: Ctrl-B then D)"
fi

echo "== Done. Bench test:  .venv/bin/python bob.py --paused"
