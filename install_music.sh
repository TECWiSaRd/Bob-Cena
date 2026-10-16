#!/usr/bin/env bash
# One-time setup of Bob's sound system on the Pi: a Bluetooth speaker and an AirPlay receiver that share the
# speaker with each other and with Bob's voice.
#
#   ./install_music.sh            set it up (asks first)
#   ./install_music.sh --yes      set it up without asking
#   ./install_music.sh --undo     turn the AirPlay receiver off and remove its settings
#
# What it changes (so you know before you run it):
#   - installs PipeWire (the audio mixer), WirePlumber, BlueZ, bluez-tools, shairport-sync, avahi and python3-dbus
#   - turns on "linger" for your user, so PipeWire and AirPlay keep running without a login
#   - sets /etc/bluetooth/main.conf "JustWorksRepairing = always" (lets a phone re-pair after you forgot it)
#   - disables shairport-sync's system service and runs it as YOUR user service instead (required with PipeWire)
#   - writes ~/.config/shairport-sync.conf and ~/.config/systemd/user/shairport-sync.service
# It does not make the Pi discoverable by Bluetooth: pairing is only open when you run /music pair.
set -euo pipefail
cd "$(dirname "$0")"

NAME="${BOB_NAME:-Bob}"
CONF="$HOME/.config/shairport-sync.conf"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT="$UNIT_DIR/shairport-sync.service"

if [ "${1:-}" = "--undo" ]; then
    systemctl --user disable --now shairport-sync 2>/dev/null || true
    rm -f "$UNIT" "$CONF"
    systemctl --user daemon-reload || true
    echo "AirPlay receiver removed. PipeWire and Bluetooth are left as they are."
    echo "Set [music] enabled = false in config.toml to switch Bob's music features off."
    exit 0
fi

case "${BOB_AIRPLAY_PASSWORD:-}" in *$'\n'*) echo "The AirPlay password can't contain a line break."; exit 1;; esac

if [ "$(id -u)" = "0" ]; then
    echo "Run this as your normal user, not with sudo (it uses sudo itself where needed)."; exit 1
fi

if [ "${1:-}" != "--yes" ]; then
    sed -n '/^# What it changes/,/^# It does not/p' "$0" | sed 's/^# \{0,1\}//'
    read -r -p "Go ahead? [y/N] " answer
    [ "$answer" = "y" ] || [ "$answer" = "Y" ] || { echo "Cancelled."; exit 0; }
fi

echo "== Packages"
sudo apt-get update
# Install one by one so a package missing on this release is reported, not fatal.
for pkg in pipewire pipewire-bin pipewire-pulse pipewire-alsa wireplumber libspa-0.2-bluetooth \
           bluez bluez-tools python3-dbus avahi-daemon shairport-sync; do
    sudo apt-get install -y "$pkg" || echo "!! could not install $pkg"
done

echo "== Keep audio services running without a login"
sudo loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable --now pipewire pipewire-pulse wireplumber 2>&1 | tail -2 || true
sudo systemctl enable --now bluetooth avahi-daemon

echo "== Bluetooth"
BTCONF="${BT_MAIN_CONF:-/etc/bluetooth/main.conf}"
if ! grep -qE '^JustWorksRepairing *= *always' "$BTCONF"; then
    sudo sed -i 's/^#*[[:space:]]*JustWorksRepairing.*/JustWorksRepairing = always/' "$BTCONF"
    grep -q '^JustWorksRepairing' "$BTCONF" || \
        echo 'JustWorksRepairing = always' | sudo tee -a "$BTCONF" >/dev/null
    sudo systemctl restart bluetooth
fi
bluetoothctl system-alias "$NAME" >/dev/null 2>&1 || true

echo "== AirPlay (shairport-sync as a user service)"
SPS="$(command -v shairport-sync || true)"
if [ -z "$SPS" ]; then
    echo "!! shairport-sync isn't installed, so AirPlay is skipped (Bluetooth still works)"
else
    sudo systemctl disable --now shairport-sync 2>/dev/null || true     # the system service can't use your PipeWire
    VERSION="$("$SPS" -V 2>&1 || true)"
    BACKEND=alsa
    echo "$VERSION" | grep -qi pulseaudio && BACKEND=pulseaudio
    echo "$VERSION" | grep -qi pipewire   && BACKEND=pipewire
    echo "shairport-sync build: $VERSION"
    echo "output backend: $BACKEND   (alsa still mixes, because pipewire-alsa routes it into PipeWire)"
    echo "$VERSION" | grep -qi dbus || echo "!! this build may lack the D-Bus interface: Bob can still hear AirPlay start/stop and duck it, but can't press play/pause on it. See the README for building a fuller one."
    mkdir -p "$UNIT_DIR"
    {
        echo 'general ='
        echo '{'
        echo "  name = \"$NAME\";"
        echo '  dbus_service_bus = "session";'
        echo '  mpris_service_bus = "session";'
        if [ -n "${BOB_AIRPLAY_PASSWORD:-}" ]; then
            pw="${BOB_AIRPLAY_PASSWORD//\\/\\\\}"      # escape \ and " so the password can't break the config file
            pw="${pw//\"/\\\"}"
            echo "  password = \"$pw\";"
        fi
        echo '};'
        echo 'sessioncontrol ='
        echo '{'
        echo '  allow_session_interruption = "yes";   // a second phone may take over instead of being refused'
        echo '  session_timeout = 20;'
        echo '};'
    } > "$CONF"
    chmod 600 "$CONF"
    cat > "$UNIT" <<EOF
[Unit]
Description=Shairport Sync, the AirPlay receiver for Bob
After=sound.target pipewire.service
Wants=pipewire.service

[Service]
ExecStart=$SPS -c $CONF -o $BACKEND --log-to-syslog
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now shairport-sync.service || echo "!! could not start the AirPlay service: journalctl --user -u shairport-sync"
fi

echo
echo "== Check"
systemctl --user is-active pipewire wireplumber shairport-sync 2>/dev/null | tr '\n' ' ' | sed 's/^/user services (pipewire wireplumber shairport-sync): /'; echo || true
bluetoothctl show 2>/dev/null | grep -E 'Alias|Powered' || true
echo
echo "Next steps:"
echo "  1. In config.toml set [music] enabled = true, copy it over, and restart Bob."
echo "  2. Pair a phone: in Bob's console type /music pair, then pick '$NAME' in the phone's Bluetooth settings."
echo "  3. AirPlay needs nothing: choose '$NAME' in the AirPlay menu on an iPhone or Mac on the same Wi-Fi."
echo "  4. If Bob's voice or the music comes out of the wrong speaker: wpctl status, then wpctl set-default <sink id>."
echo "  AirPlay is open to everyone on your Wi-Fi unless you re-run this with BOB_AIRPLAY_PASSWORD='something' set."
