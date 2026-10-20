# Manual 21: Powering the Pi off

Anyone using Bob, from the console, the shared console, or the phone dashboard, can shut the Pi down cleanly.
This manual explains how it works, who is allowed, and what to do first on a new Pi.

**One thing to know before you use it:** once the Pi is off, **nobody can switch it back on from a distance**.
Someone has to unplug the power and plug it in again (or press a power button if you've fitted one). That's why
it takes two steps, and why Claude can't do it.

---

## How to do it

### From the console (yours or the shared one)

```
/shutdown            Bob explains what will happen and waits for your OK
/shutdown confirm    within 30 seconds: the Pi powers off
/shutdown cancel     change your mind
```

### From the phone dashboard

Scroll to the bottom and press **Shut down the Pi**. The phone asks "Shut down the Pi?" first. If you press OK,
it sends both steps for you.

## What happens

1. Bob says "Shutting down now. Goodbye!"
2. He stops the wheels, switches off the motor driver, and closes everything down cleanly, the same as `/quit`.
3. Only then does the Pi power off, so nothing is cut off mid-move or mid-write.
4. People attached to the shared console see the connection close.

If the emergency stop is on, shutdown still works.

## Who can do it

Set in `[power]` in `config.toml`:

| Kind of user | Default | Who that is |
|---|---|---|
| `owner` | allowed | you, at Bob's own console |
| `operator` | allowed | friends in the `bobops` group on the shared console |
| `dashboard` | allowed | anyone with a working dashboard token |
| `viewer` | **not allowed** | watch-only users (`bobview` group). They can watch and press the emergency stop, and I kept powering off off that list on purpose |

To change it: `who = ["owner", "operator", "dashboard", "viewer"]`. To turn the whole feature off:
`enabled = false`.

The confirmation is tied to the person: if Kai types `/shutdown`, only Kai can confirm it, and only within
`confirm_seconds` (30). Every shutdown is logged and recorded in the timeline with the person's name.

## First-time setup on the Pi

Bob needs permission to power off without asking for a password. Check with `/check`: the line `power off`
should say it works. Raspberry Pi OS set up through Raspberry Pi Imager usually allows this already. If it says
the account "isn't allowed to power the Pi off without a password", run, as your normal user:

```bash
cd ~/bob
./install_power.sh
```

It tells you what it will change, asks first, and adds **one** rule: your account may run exactly
`shutdown -h now` without a password, and nothing else. It checks the rule with `visudo` before installing it,
because a broken sudoers file can lock you out of `sudo`. Remove it later with `./install_power.sh --undo`.

## Safety notes

- **Claude cannot do this.** There is no tool for it. Only people with access can.
- **Two steps by the same person** stop accidents (a mistyped command, a stray button press).
- **Dashboard tokens can power the Pi off.** When you give a friend a dashboard token, this is one of the things
  it allows. Remove `"dashboard"` from `who` if you'd rather they couldn't.
- In **simulation** (`--sim`) nothing ever powers off the computer you're on: Bob quits and says what the Pi
  would have done.
- If the power-off command fails after Bob has quit, the reason is in `logs/bob.log` and Bob has already
  stopped, so check there, and run `sudo shutdown -h now` by hand if needed.

## Settings (`[power]`)

| Setting | Default | What it does |
|---|---|---|
| `enabled` | true | allow `/shutdown` |
| `who` | `["owner", "operator", "dashboard"]` | which kinds of user may use it (`viewer` can be added) |
| `confirm_seconds` | 30 | how long you have to type `/shutdown confirm` |

## Troubleshooting

| Problem | Fix |
|---|---|
| `can't power off: this account isn't allowed ...` | run `./install_power.sh` on the Pi |
| `powering the Pi off from here isn't allowed for your kind of user` | add your kind of user to `who` in `[power]` |
| `type /shutdown first, then /shutdown confirm` | you waited longer than `confirm_seconds`, or someone else made the request: start again |
| No "Shut down the Pi" button on the dashboard | `"dashboard"` isn't in `who`, or `enabled = false` |
| Bob quit but the Pi stayed on | see `logs/bob.log` for the reason, then `sudo shutdown -h now` |
| I shut it down and now it won't answer | unplug the power, wait a few seconds, plug it back in |
