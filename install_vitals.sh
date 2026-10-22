#!/usr/bin/env bash
# Records the Pi's vital signs every 10 seconds, from boot, to /var/log/bob-vitals.log, so that after a crash or a power
# cut you can see what the Pi was doing just before: load, memory, temperature, power problems, Wi-Fi signal, whether it
# could still reach the router, and whether Bob was running.
#
#   ./install_vitals.sh               install the recorder (asks first)
#   ./install_vitals.sh --watchdog    also switch on the hardware watchdog: a Pi that freezes completely reboots itself
#                                     after about 15 seconds, instead of staying dead until someone unplugs it
#   ./install_vitals.sh --undo        remove both
#
# Read the log with:   tail -40 /var/log/bob-vitals.log     (the file keeps the last ~10 MB, over a few days)
set -euo pipefail

SCRIPT=/usr/local/bin/bob-vitals
UNIT=/etc/systemd/system/bob-vitals.service
WATCHDOG=/etc/systemd/system.conf.d/bob-watchdog.conf
LOG=/var/log/bob-vitals.log

want_watchdog=0
yes=0
action=install
for arg in "$@"; do
    case "$arg" in
        --watchdog) want_watchdog=1 ;;
        --undo) action=undo ;;
        --yes) yes=1 ;;
        -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
        *) echo "unknown option: $arg"; exit 2 ;;
    esac
done

if [ "$action" = undo ]; then
    sudo systemctl disable --now bob-vitals.service 2>/dev/null || true
    sudo rm -f "$UNIT" "$SCRIPT" "$WATCHDOG"
    sudo systemctl daemon-reload
    echo "Removed. The log (${LOG}) was left in place; delete it yourself if you like."
    echo "If you had the watchdog on, it stops after the next reboot."
    exit 0
fi

echo "This will:"
echo "  - install ${SCRIPT} and a service (bob-vitals) that appends one line every 10 s to ${LOG}"
[ "$want_watchdog" = 1 ] && echo "  - switch on the hardware watchdog (${WATCHDOG}): takes effect after a reboot"
if [ "$yes" != 1 ]; then
    read -r -p "Go ahead? [y/N] " answer
    case "$answer" in y|Y|yes) ;; *) echo "Cancelled."; exit 1 ;; esac
fi

sudo tee "$SCRIPT" >/dev/null <<'EOS'
#!/usr/bin/env bash
# One line every 10 seconds. Everything is best effort: a missing tool leaves its field empty.
LOG=/var/log/bob-vitals.log
while true; do
    gw=$(ip route 2>/dev/null | awk '/^default/{print $3; exit}')
    if [ -n "$gw" ] && ping -c1 -W1 "$gw" >/dev/null 2>&1; then net="router-ok"; else net="ROUTER-UNREACHABLE"; fi
    line="$(date '+%F %T') up=$(cut -d' ' -f1 /proc/uptime | cut -d. -f1)s"
    line="$line load=$(cut -d' ' -f1-3 /proc/loadavg)"
    line="$line mem_used=$(free -m | awk '/Mem/{print $3}')MB avail=$(free -m | awk '/Mem/{print $7}')MB"
    line="$line temp=$(vcgencmd measure_temp 2>/dev/null | cut -d= -f2) $(vcgencmd get_throttled 2>/dev/null)"
    line="$line wifi=$(iw dev wlan0 link 2>/dev/null | awk '/signal:/{print $2$3}') $net"
    line="$line bob=$(pgrep -fc 'bob.py' || true)"
    echo "$line" >> "$LOG"
    sync "$LOG" 2>/dev/null || true
    if [ "$(stat -c %s "$LOG" 2>/dev/null || echo 0)" -gt 5000000 ]; then mv -f "$LOG" "$LOG.1"; fi
    sleep 10
done
EOS
sudo chmod 755 "$SCRIPT"

sudo tee "$UNIT" >/dev/null <<EOS
[Unit]
Description=Bob: record the Pi's vital signs
After=local-fs.target

[Service]
ExecStart=$SCRIPT
Restart=always
Nice=10

[Install]
WantedBy=multi-user.target
EOS
sudo systemctl daemon-reload
sudo systemctl enable --now bob-vitals.service

if [ "$want_watchdog" = 1 ]; then
    if [ ! -e /dev/watchdog ]; then
        echo "No /dev/watchdog on this Pi, so the watchdog was NOT set up."
    else
        sudo mkdir -p "$(dirname "$WATCHDOG")"
        sudo tee "$WATCHDOG" >/dev/null <<'EOS'
[Manager]
RuntimeWatchdogSec=15
RebootWatchdogSec=2min
EOS
        echo "Watchdog configured. It starts after the next reboot (sudo reboot)."
    fi
fi

echo
echo "Done. Wait 15 seconds, then:  tail -3 ${LOG}"
echo "After the next crash, power the Pi back on and run:  tail -60 ${LOG}"
