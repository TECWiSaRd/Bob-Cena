#!/usr/bin/env bash
# Copy Bob's code from this Mac to the Pi.
#
#   ./deploy.sh                 copy to adam@bob
#   ./deploy.sh kai@bobcena     copy to another login or address
#   ./deploy.sh --dry-run       show what WOULD be copied, change nothing
#
# It leaves out the app folder, the git history, and the Pi's own data and secrets (.env, memory, tuning, certificates,
# paired devices...): see .rsync-exclude. Restart Bob afterwards (/quit and start him again, or sudo systemctl restart bob).
set -euo pipefail
cd "$(dirname "$0")"

DRY=""
HOST="${BOB_HOST:-adam@bob}"
for arg in "$@"; do
    case "$arg" in
        --dry-run|-n) DRY="--dry-run" ;;
        -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
        -*) echo "unknown option: $arg"; exit 2 ;;
        *) HOST="$arg" ;;
    esac
done

command -v rsync >/dev/null || { echo "rsync isn't installed"; exit 1; }
rsync -av $DRY --exclude-from=.rsync-exclude ./ "$HOST:~/bob/"
echo
echo "${DRY:+(dry run: nothing was copied) }Done. Restart Bob to run the new code."
