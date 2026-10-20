#!/usr/bin/env bash
# Lets Bob power the Pi off (the /shutdown command) without asking for a password.
#
#   ./install_power.sh          set it up (asks first)
#   ./install_power.sh --yes    set it up without asking
#   ./install_power.sh --undo   remove it again
#
# A Pi set up with Raspberry Pi Imager usually allows this already; /check says "power off ... works" if so.
#
# What it changes (so you know before you run it):
#   - adds ONE rule to /etc/sudoers.d/bob-power: your account may run exactly "shutdown -h now" without a password.
#     Nothing else is allowed by it. The file is checked with visudo before it is installed, because a broken
#     sudoers file can lock you out of sudo.
set -euo pipefail
cd "$(dirname "$0")"

SUDO="${BOB_SUDO:-sudo}"
FILE="${BOB_SUDOERS_FILE:-/etc/sudoers.d/bob-power}"
OWNER="${BOB_OWNER:-$USER}"
INSTALL_OWNER="${BOB_INSTALL_OWNER-"-o root -g root"}"      # the file must belong to root (tests change this)
SHUTDOWN="${BOB_SHUTDOWN_PATH:-$(readlink -f "$(command -v shutdown 2>/dev/null || echo /usr/sbin/shutdown)")}"

if [ "${1:-}" = "--undo" ]; then
    $SUDO rm -f "$FILE"
    echo "Removed $FILE. /shutdown will say it isn't allowed unless sudo already permits it."
    exit 0
fi
if [ "$(id -u)" = "0" ]; then
    echo "Run this as your normal user (the account Bob runs as), not with sudo."; exit 1
fi
case "$OWNER" in *[!A-Za-z0-9._-]*|"") echo "Unexpected account name '$OWNER'; refusing to write a sudoers rule."; exit 1;; esac
case "$SHUTDOWN" in /*) ;; *) echo "Couldn't find the shutdown program."; exit 1;; esac

if [ "${1:-}" != "--yes" ]; then
    sed -n '/^# What it changes/,$p' "$0" | sed 's/^# \{0,1\}//'
    read -r -p "Go ahead? [y/N] " answer
    [ "$answer" = "y" ] || [ "$answer" = "Y" ] || { echo "Cancelled."; exit 0; }
fi

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
printf '# Lets Bob (account %s) power the Pi off. Added by install_power.sh.\n%s ALL=(root) NOPASSWD: %s -h now\n' \
    "$OWNER" "$OWNER" "$SHUTDOWN" > "$TMP"

# Never install a sudoers file that sudo itself can't read: that could lock everyone out.
if ! $SUDO visudo -c -f "$TMP" >/dev/null; then
    echo "The rule didn't pass visudo's check, so nothing was installed."; exit 1
fi
# shellcheck disable=SC2086
$SUDO install -m 0440 $INSTALL_OWNER "$TMP" "$FILE"
echo "Done. $OWNER may now run:  $SHUTDOWN -h now   without a password."
echo "Check it with  /check  in Bob's console (the 'power off' line)."
