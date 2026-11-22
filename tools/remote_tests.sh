#!/usr/bin/env bash
# Run Bob's Python tests on a spare Raspberry Pi (for example Lyra) instead of this Mac, so the Mac stays fast.
#
#   tools/remote_tests.sh adam@192.168.1.50                    run the whole suite there
#   tools/remote_tests.sh adam@192.168.1.50 tests.test_ble     run just some tests (anything `python -m unittest` takes)
#   BOB_TESTS_DIR=bob-tests tools/remote_tests.sh ...          the folder on the Pi (default ~/bob-tests)
#   BOB_SSH_OPTS="-o HostKeyAlias=lyra.lan" tools/remote_tests.sh ...   extra ssh options (for an address your Mac hasn't met before)
#
# It copies the project into its OWN folder on the Pi (~/bob-tests, never ~/bob), so a robot that is running there is not touched: no
# config.local.toml, .env, memory or certificates are copied (the same files deploy.sh leaves out), and no test talks to hardware. The first run
# makes a virtual environment there and installs what the tests need, which takes a few minutes; later runs are quick.
# The app's own (Dart) tests need the Flutter SDK and stay on the Mac. Do not run this on a Pi whose robot you are using at that moment: the
# tests are heavy for a little Pi.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ $# -lt 1 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    sed -n '2,13p' "$0"
    exit 0
fi
HOST="$1"; shift
DIR="${BOB_TESTS_DIR:-bob-tests}"
SSH_OPTS="${BOB_SSH_OPTS:-}"
command -v rsync >/dev/null || { echo "rsync isn't installed"; exit 1; }

echo "== Copying the project to $HOST:~/$DIR (not ~/bob)"
# (the app and workflow folders are left out as a whole, but a few small files in them are read by tests: the version in pubspec.yaml, the Dart
# test files whose numbers Python checks, the Android build script, and the workflow that signs the Android release)
rsync -a -e "ssh $SSH_OPTS" \
    --include=/.github/ --include='/.github/***' --include=/app/ --include=/app/pubspec.yaml --include='/app/test/***' --include=/app/android/ --include=/app/android/app/ \
    --include=/app/android/app/build.gradle.kts --exclude='/app/android/*' --exclude='/app/android/app/*' --exclude='/app/*' \
    --exclude-from=.rsync-exclude --exclude=/.venv --exclude=/captures ./ "$HOST:~/$DIR/"

echo "== Running the tests on $HOST (the first time this also sets up Python there)"
ssh $SSH_OPTS "$HOST" bash -s -- "$DIR" "$@" <<'REMOTE'
set -e
DIR="$1"; shift
cd "$HOME/$DIR"
if [ ! -x .venv/bin/python ]; then
    echo "-- making a virtual environment"
    python3 -m venv --system-site-packages .venv
    .venv/bin/pip install -q --upgrade pip || true
fi
.venv/bin/pip install -q -r requirements.txt 2>&1 | tail -2 || true
# OpenCV and numpy make the colour, tag and calibration tests run; without them those tests are skipped, which is fine but says less.
.venv/bin/python -c "import numpy, cv2" 2>/dev/null || .venv/bin/pip install -q numpy opencv-contrib-python-headless 2>&1 | tail -2 || echo "(no OpenCV here: the picture tests will be skipped)"
echo "-- $(.venv/bin/python --version), $(nproc) cores, $(free -m | awk '/Mem:/{print $2}') MB"
# at low priority, so a robot running on this Pi keeps its share of the CPU
if [ $# -gt 0 ]; then
    nice -n 15 .venv/bin/python -m unittest "$@"
else
    nice -n 15 .venv/bin/python -m unittest discover -s tests
fi
REMOTE
