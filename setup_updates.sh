#!/usr/bin/env bash
# Let Bob update himself from GitHub (/update) by turning this folder into a git checkout of your repository.
#
#   ./setup_updates.sh                          set it up (asks before each step)
#   ./setup_updates.sh --repo OWNER/NAME        a different repository (default: TECWiSaRd/Bob-Cena)
#
# It makes a read-only "deploy key" for this Pi (it can fetch your code but never change it), backs up this folder,
# and lines it up with the repository. Your .env, notes, tuning, logs and config.local.toml are not touched.
set -euo pipefail

REPO="TECWiSaRd/Bob-Cena"
while [ $# -gt 0 ]; do
    case "$1" in
        --repo) REPO="${2:?--repo needs OWNER/NAME}"; shift 2 ;;
        -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
        *) echo "unknown option: $1"; exit 2 ;;
    esac
done
case "$REPO" in
    */*) ;;
    *) echo "--repo should look like OWNER/NAME"; exit 2 ;;
esac
HERE="$(cd "$(dirname "$0")" && pwd)"
KEY="$HOME/.ssh/bob_deploy"
HOSTALIAS="github-bob"

command -v git >/dev/null || { echo "git isn't installed: sudo apt-get install -y git"; exit 1; }

if [ -d "$HERE/.git" ]; then
    echo "This folder is already a git checkout:"
    git -C "$HERE" remote -v | head -2
    echo "Nothing to do. Try /update in Bob's console."
    exit 0
fi

echo "This will:"
echo "  1. make a read-only deploy key for this Pi ($KEY) if there isn't one"
echo "  2. add a 'Host $HOSTALIAS' entry to ~/.ssh/config"
echo "  3. back up this folder to ~/bob-backup-<date>.tar.gz"
echo "  4. turn $HERE into a checkout of github.com/$REPO (main)"
read -r -p "Go ahead? [y/N] " answer
case "$answer" in y|Y|yes) ;; *) echo "Cancelled."; exit 1 ;; esac

mkdir -p "$HOME/.ssh"; chmod 700 "$HOME/.ssh"
[ -f "$KEY" ] || ssh-keygen -t ed25519 -N "" -C "bob-deploy@$(hostname)" -f "$KEY" >/dev/null
if ! grep -q "^Host $HOSTALIAS\$" "$HOME/.ssh/config" 2>/dev/null; then
    cat >> "$HOME/.ssh/config" <<EOS

Host $HOSTALIAS
    HostName github.com
    User git
    IdentityFile $KEY
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new
EOS
    chmod 600 "$HOME/.ssh/config"
fi

echo
echo "Add this public key to GitHub as a READ-ONLY deploy key:"
echo "  https://github.com/$REPO/settings/keys/new   (leave 'Allow write access' UNticked)"
echo
cat "$KEY.pub"
echo
read -r -p "Press Enter once you've added it..." _

if ! ssh -T -o BatchMode=yes "git@$HOSTALIAS" 2>&1 | grep -qi "successfully authenticated"; then
    echo "GitHub didn't accept the key yet. Check it was added to $REPO, then run this script again."
    exit 1
fi

BACKUP="$HOME/bob-backup-$(date +%Y%m%d-%H%M%S).tar.gz"
tar -czf "$BACKUP" -C "$(dirname "$HERE")" --exclude='.venv' "$(basename "$HERE")"
echo "Backed up to $BACKUP"

cd "$HERE"
git init -q -b main
git remote add origin "git@$HOSTALIAS:$REPO.git"
git fetch -q origin main
git checkout -q -f -B main origin/main
git branch -q --set-upstream-to=origin/main main
echo
echo "Done: $(git log --oneline -1)"
echo "Your .env, notes and settings were left alone. In Bob's console, /update now shows what is new."
