# Manual 23: Alerts, versions and updates

Three things that stop Bob being a mystery when you are not looking at him: **alerts** (he tells you when something is
wrong, and you find out if he goes quiet), **/version** (which code is this?), and **/update** (install the newest code
from GitHub without copying files).

**Status:** tested with pretend web services and a pretend GitHub (real git repositories on this computer). None of it has been
tried on the real Pi, with a real phone or with the real GitHub yet.

---

## Alerts

Two optional addresses, both kept in `.env` (never in `config.toml`, so they cannot be committed by accident):

| `.env` line | What it is | What it does |
|---|---|---|
| `HEARTBEAT_URL=...` | a "dead man's switch", for example a free check on healthchecks.io | Bob pings it every minute with a line of vital signs. If the pings **stop**, that service messages you. A frozen Pi can't report itself; a missing heartbeat can. |
| `NOTIFY_URL=...` | a push-notification address, for example an ntfy topic such as `https://ntfy.sh/pick-a-long-secret-name` | Bob sends short messages here when something needs attention. |

Switch it on in `config.local.toml`:
```toml
[alerts]
enabled = true
```

### Set up the phone notifications (ntfy, free)
1. Install the **ntfy** app on your phone.
2. Subscribe to a topic with a long random name, for example `bob-7f3k29xq81`. Anyone who knows the name can read and send, so
   treat it like a password.
3. Put `NOTIFY_URL=https://ntfy.sh/bob-7f3k29xq81` in `.env` on the Pi, restart Bob, and type `/alerts test`.

### Set up the heartbeat (healthchecks.io, free)
1. Make a check with a **period of 1 minute and a grace time of 3 minutes**, and set where it should message you.
2. Copy its ping address into `.env` as `HEARTBEAT_URL=https://hc-ping.com/...` and restart Bob.

### What Bob tells you about
| Event | When | In the default list? |
|---|---|---|
| `restart` | Bob started again after an unexpected stop: a crash, a freeze or a power cut. He notices because he didn't shut down cleanly last time | yes |
| `estop` | the emergency stop was pressed, and by whom | yes |
| `camera` | the camera driver hung and Bob is restarting himself | yes |
| `power` | someone confirmed `/shutdown` | yes |
| `update` | an update was installed (or failed) | yes |
| `vitals` | the Pi is hot (80 C+), has weak power, is nearly out of disk or memory (once an hour each) | yes |
| `start`, `stopped` | every start and every clean stop | no (add them to `notify` if you want them) |

Each kind is limited to one message every 5 minutes (`cooldown_s`), so a loop can never flood your phone. Change the list with
`notify = ["restart", "estop", ...]`.

**What is sent:** short text only (for example "Emergency stop (console)"), plus vital signs in the heartbeat. Never a camera picture
or anything the microphone heard. Messages are sent from a background thread: a slow or unreachable service can't hold Bob up.
Claude has no way to send alerts.

`/alerts` shows whether it works (the address is shown without its secret part), and `/alerts test` sends a test message.

## /version

`/version` shows the code version, a short fingerprint of all the code files, the date of the newest file, and the git state:
```
Bob 26.11-dev, code 3f9a1c2e, newest file 2026-10-22 18:04, git 8c1ec3a
```
Two Pis with the same fingerprint run the same code. A Pi that holds a mix of old and new files (a copy that stopped half way)
shows a different one. The shared console also compares: if a friend's `bob-console` copy is out of date, they see a warning
and the owner runs `./install_remote.sh --yes`.

## /update: install the newest code from GitHub

`/update` only works when Bob's folder is a **git checkout**. Until now you copied files with `rsync`; that still works, but
`/update` is safer: it takes a whole, matching set of files.

### One-time setup (on the Pi)
```bash
cd ~/bob
./setup_updates.sh
```
It makes a **read-only deploy key** for this Pi (it can fetch your code but can never change it), asks you to add that key at
`github.com/<you>/<repo>/settings/keys` (leave "Allow write access" unticked), backs up the folder to `~/bob-backup-<date>.tar.gz`,
and lines the folder up with GitHub. Your `.env`, notes, tuning, logs, `usage.json` and `config.local.toml` are not touched.

### Using it (owner only)
```
/update            looks on GitHub and lists what is new
/update confirm    within a minute: installs it
```
Bob pulls fast-forward only, checks that every file still compiles, installs new requirements, and **puts the old code back if
anything is wrong**. If files here were changed by hand it refuses rather than overwrite them. Under the service he then
quits and the service starts the new code a few seconds later; started by hand, he tells you to restart him yourself.
Claude cannot update Bob.

**Push from your Mac first.** `/update` installs what is on GitHub, so commit and push there, then `/update` on the Pi.

## Troubleshooting

| Problem | Fix |
|---|---|
| `/alerts` says neither address is set | add `HEARTBEAT_URL` and/or `NOTIFY_URL` to `.env` and restart |
| `isn't a web address` | the line in `.env` must start with `https://` |
| `/alerts test` says queued but nothing arrives | check the topic name matches in the ntfy app; `/alerts` shows how many were sent and failed |
| Heartbeat shows a problem | the Pi can't reach the service: check its Wi-Fi |
| `/update`: `couldn't reach GitHub` | the deploy key isn't set up or was removed: run `./setup_updates.sh` again |
| `/update`: `isn't a git checkout` | run `./setup_updates.sh` once |
| `/update`: `files here were changed by hand` | `cd ~/bob && git status`, then `git checkout -- FILE` to undo a hand edit |
| `/update`: `the new code didn't pass its checks` | nothing was changed; the message names the file. Fix it on the Mac and push again |
