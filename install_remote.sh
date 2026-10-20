#!/usr/bin/env bash
# Shared console: lets friends who have their own login on the Pi attach to Bob's console WITHOUT getting a shell
# on your account. They type `bob-console` and see (and, if you allow, use) the same screen you do.
#
#   ./install_remote.sh                    set it up (asks first)
#   ./install_remote.sh --yes              set it up without asking
#   ./install_remote.sh --add NAME         let the Pi user NAME run commands (adds them to the 'bobops' group)
#   ./install_remote.sh --add NAME --view  let NAME watch only (and use the emergency stop): the 'bobview' group
#   ./install_remote.sh --remove NAME      take NAME out of both groups
#   ./install_remote.sh --undo             remove the bob-console command
#
# What it changes (so you know before you run it):
#   - creates two groups, bobops and bobview
#   - copies console.py and remote.py to /opt/bob-console (so every user can run the viewer; your home stays private)
#   - installs the command /usr/local/bin/bob-console, which refuses to talk to a socket your account doesn't own
# It does not open any network port. After this, set  [remote] enabled = true  in config.toml and restart Bob.
# Run it again after updating Bob's code, so friends get the updated viewer.
set -euo pipefail
cd "$(dirname "$0")"

SUDO="${BOB_SUDO:-sudo}"
OPT_DIR="${BOB_OPT_DIR:-/opt/bob-console}"
BIN_DIR="${BOB_BIN_DIR:-/usr/local/bin}"
SOCKET="${BOB_CONSOLE_SOCKET:-/tmp/bob-console.sock}"
OWNER="${BOB_OWNER:-$USER}"
OPS=bobops
VIEW=bobview

need_user() {
    [ -n "${1:-}" ] || { echo "Give the Pi user's name, for example: $0 --add kai"; exit 1; }
    id "$1" >/dev/null 2>&1 || { echo "There is no Pi user called '$1'."; exit 1; }
    [ "$1" != "$OWNER" ] || { echo "$1 is you: the account Bob runs as already has full access."; exit 1; }
}

case "${1:-}" in
    --add)
        need_user "${2:-}"
        group="$OPS"; [ "${3:-}" = "--view" ] && group="$VIEW"
        getent group "$group" >/dev/null || { echo "Run $0 first to create the groups."; exit 1; }
        $SUDO usermod -aG "$group" "$2"
        # Anyone with sudo can already read everything; say so, because a group is not much protection then.
        if id -nG "$2" | tr ' ' '\n' | grep -qx sudo; then
            echo "!! $2 is in the 'sudo' group: they can already do anything on this Pi, including read your API key."
            echo "   Remove them with: sudo gpasswd -d $2 sudo"
        fi
        echo "$2 can now run  bob-console  ($([ "$group" = "$VIEW" ] && echo "watch only" || echo "commands allowed")). No re-login needed."
        exit 0;;
    --remove)
        need_user "${2:-}"
        for g in "$OPS" "$VIEW"; do
            if id -nG "$2" | tr ' ' '\n' | grep -qx "$g"; then $SUDO gpasswd -d "$2" "$g" >/dev/null; fi
        done
        echo "$2 can no longer use the shared console."
        exit 0;;
    --undo)
        $SUDO rm -f "$BIN_DIR/bob-console"
        $SUDO rm -rf "$OPT_DIR"
        echo "Removed bob-console. The groups $OPS and $VIEW are left in place (delete them with: sudo groupdel $OPS; sudo groupdel $VIEW)."
        echo "Set [remote] enabled = false in config.toml to close the socket."
        exit 0;;
esac

if [ "$(id -u)" = "0" ]; then
    echo "Run this as your normal user (the account Bob runs as), not with sudo."; exit 1
fi
if [ "${1:-}" != "--yes" ]; then
    sed -n '/^# What it changes/,/^# Run it again/p' "$0" | sed 's/^# \{0,1\}//'
    read -r -p "Go ahead? [y/N] " answer
    [ "$answer" = "y" ] || [ "$answer" = "Y" ] || { echo "Cancelled."; exit 0; }
fi

echo "== Groups"
for g in "$OPS" "$VIEW"; do
    getent group "$g" >/dev/null || $SUDO groupadd "$g"
done

echo "== Viewer program"
$SUDO install -d -m 755 "$OPT_DIR"
$SUDO install -m 644 console.py remote.py "$OPT_DIR/"
$SUDO tee "$BIN_DIR/bob-console" >/dev/null <<WRAP
#!/bin/sh
# Attach to Bob's shared console. Refuses a socket that $OWNER's account doesn't own.
exec python3 "$OPT_DIR/remote.py" --owner "$OWNER" --socket "$SOCKET" "\$@"
WRAP
$SUDO chmod 755 "$BIN_DIR/bob-console"

echo
echo "Done. Next:"
echo "  1. In config.toml set   [remote]  enabled = true   then copy it over and restart Bob."
echo "  2. Let a friend in:     ./install_remote.sh --add NAME        (or --add NAME --view to watch only)"
echo "  3. They connect with SSH and type:  bob-console"
echo "  Check who is attached with  /who  in Bob's console."
