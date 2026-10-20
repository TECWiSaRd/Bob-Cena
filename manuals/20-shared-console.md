# Manual 20: Shared console

Several people can use the same running Bob, each from their own login on the Pi, **without a shell on the
owner's account**. Everyone sees the same screen: the same log, the same status bar, and a command line each.
This manual explains how it works, how to set it up, and what each kind of user can do.

**Status:** tested with real local sockets and with the real curses screen in a terminal. One piece can only
be checked on the Pi itself: how Linux tells Bob who is connecting. I tested my reading of that, but not on
Linux, so try it with a real friend login and tell me if anything is off.

---

## The idea

Bob (the program running as the **owner**, `adam` in these manuals) opens a local socket. A friend with their
own Pi login types `bob-console`, and the screen on their terminal is Bob's console. Linux itself says who is
connecting, so nobody can pretend to be someone else, and nothing they type reaches a shell.

```
  adam (owner)       tmux: the usual console
  kai  (operator)    $ bob-console   ──┐
  sam  (viewer)      $ bob-console   ──┼──►  Bob's socket  ──►  the same Bob
                                       │      (who is who comes from Linux)
```

Compare with the other ways in:

| Way | What they can reach | Use it for |
|---|---|---|
| **Shared console** (this manual) | Bob's console only | friends with a Pi login |
| Phone dashboard ([manual 07](07-camera-stream-and-dashboard.md)) | a safe set of commands, no login needed | friends who just want buttons |
| Sharing your tmux session | **a shell as you**, including your API key | co-owners you'd give your own login |

## What each person can do

| Role | Who | Can do |
|---|---|---|
| **Owner** | the account Bob runs as | everything, including `/quit` |
| **Operator** | members of the `bobops` group | every command except those in `deny` (by default just `/quit`), drive by hand, push-to-talk, emergency stop |
| **Viewer** | members of the `bobview` group | watch, and press **Space** (the emergency stop). Anything else is refused with a note |
| Anyone else | | refused, with a message saying how to get added |

Everything an operator types is recorded **under their name**: the log shows `> [kai] /say hi`, a plain
message reaches Bob as `[kai] hello`, and the [timeline](14-memory-and-people.md) records who did what. Anyone
can use the emergency stop, and it is recorded who pressed it.

---

## Setting it up (you, the owner)

On the Pi, in Bob's folder, as your normal user:

```bash
cd ~/bob
./install_remote.sh
```
It tells you what it will change, asks first, and then:
- creates the two groups `bobops` and `bobview`
- copies the viewer (two small files) to `/opt/bob-console`, which every user can read even though your home
  folder is private
- installs the command `/usr/local/bin/bob-console`, which refuses to connect to a socket your account
  doesn't own

Then:

1. In `config.toml` set `enabled = true` under `[remote]`, copy it over, and restart Bob.
2. Let a friend in:
   ```bash
   ./install_remote.sh --add kai            # kai can run commands
   ./install_remote.sh --add sam --view     # sam can only watch (and use the emergency stop)
   ```
   Take someone out with `./install_remote.sh --remove kai`.
3. They connect with SSH and type `bob-console`.

Check it any time with `/who` in Bob's console, or `/check` (it has a `shared console` line):
```
on /tmp/bob-console.sock; kai (operator), sam (viewer)
```

**After updating Bob's code,** run `./install_remote.sh --yes` again, so friends get the updated viewer.

### Warnings from the installer

- If it says a user is in the **`sudo` group**, that person can already do anything on the Pi, including read
  your API key, whatever groups they're in. Remove them with `sudo gpasswd -d NAME sudo`.
- Keep your home folder private (`chmod 750 /home/adam`, or `700`). Then other logins can't read your notes, photos
  or `.env`, and they can't see the socket's folder either. The socket itself is in `/tmp` so they can reach it.

---

## Using it (your friend)

```bash
ssh kai@bob            # their own login on the Pi
bob-console
```
They see the same screen as the owner's console:

| Key | Does |
|---|---|
| type and Enter | send a message to Bob, or a `/command` |
| **Space** (empty line) | emergency stop (works for viewers too) |
| **Tab** (empty line) | push-to-talk (operators) |
| Page Up / Down | scroll |
| **Ctrl-C** | leave. Bob keeps running; it doesn't quit him |

Their name is shown on the status bar after `|`: `kai (operator)` or `sam (viewer, view only)`.

Everyone sees every command and answer. If two people give conflicting commands, the latest one wins, and the
speed cap and every other safety limit still apply. `/drive` (keyboard driving) is shared too: when one person
turns it on, it's on for all, so tell people before you use it.

---

## Settings (`[remote]` in `config.toml`)

| Setting | Default | What it does |
|---|---|---|
| `enabled` | false | open the shared console |
| `socket` | `"/tmp/bob-console.sock"` | where it listens. Change it only with a matching `--socket` for `bob-console` |
| `operators` | `["bobops"]` | Linux groups whose members may run commands |
| `viewers` | `["bobview"]` | Linux groups that may only watch |
| `deny` | `["quit"]` | commands only the owner may run (add others, such as `"forget"`, if you want) |
| `max_clients` | 4 | how many people may be attached at once |

## How it stays safe

- **Linux tells Bob who is connecting.** A person can't claim to be someone else, and a name isn't typed in.
- **Groups decide what they may do.** Not in a group means refused. Viewers can't command.
- **No shell.** The only thing a friend gets is Bob's console. They can't reach `.env`, your files, or your
  account through it.
- **The viewer won't talk to an impostor.** `bob-console` checks that the socket is owned by your account
  before connecting, so another user can't put a fake one in `/tmp` and read what a friend types.
- **Slow or abusive clients can't hurt Bob.** Messages are size-limited and rate-limited, garbage is ignored,
  a client that can't keep up loses its oldest log lines instead of slowing Bob, and `max_clients` caps the
  number of connections.
- **Bob doesn't change when nobody is attached.** The socket does nothing until someone connects.

## Troubleshooting

| Problem | Fix |
|---|---|
| `bob-console: command not found` | run `./install_remote.sh` on the Pi (as the owner) |
| `Bob isn't running, or the shared console is off` | start Bob, and check `enabled = true` under `[remote]` |
| `... isn't allowed: ask the owner to add you` | the owner runs `./install_remote.sh --add NAME` |
| `that socket isn't owned by Bob's account` | the socket isn't Bob's. Don't continue; tell the owner |
| `/quit is only for the owner` | by design (the `deny` list) |
| `view-only: you can watch...` | the user is in the `bobview` group |
| `too many people are attached` | raise `max_clients`, or someone should leave |
| `Shared console off: ... needs Linux` | it only runs on the Pi, not on a Mac |
| `Shared console off: another Bob is already using it` | a second Bob is running, or use a different `socket` |
| Screen garbled | make the terminal bigger (at least 100 columns) |
