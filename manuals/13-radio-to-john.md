# Manual 13: Radio to John

Bob can talk to **John**, your friend's robot, over Bluetooth or over Wi-Fi. Claude sends John short messages and reads
his replies, and you can watch the whole conversation.

> **Status:** the message format, signing and connection logic are tested with two simulated robots, and the
> Wi-Fi link is tested over real network connections on one computer. **Neither link has been tried between
> two real robots yet**, and the radio is switched off until both robots are set up.

---

## How it works

- **The link.** Bob waits for a connection (`role = "listen"`) and John connects to him (`role =
  "connect"`), using Bob's Bluetooth address. If the link drops, it reconnects by itself.
- **Signed messages.** Both robots share a secret password (`BOB_RADIO_SECRET`). Every message is signed
  with it, so Bob ignores anything from a stranger, even one who manages to connect.
- **Claude's side.** Bob has a `radio_send` tool. John's messages appear in Bob's next status report, under
  "Messages from John", as quoted text.

## Bluetooth or Wi-Fi?

| | Bluetooth (`transport = "bluetooth"`) | Wi-Fi (`transport = "wifi"`) |
|---|---|---|
| Range | the same room or building | anywhere the two robots can reach each other: the same Wi-Fi, or different houses over a VPN |
| Setup | pair the two Pis | give the caller the other robot's address |
| Privacy | encrypted once paired | signed, **not encrypted**: fine on a home network, use a VPN across the internet |
| Wi-Fi interference | Bluetooth and Wi-Fi share the antenna | none |

Everything else (the secret, the commands, the safety rules) is the same. Use Wi-Fi when the robots are in
different houses; Bob is often at a friend's house, which is where Bluetooth range is no help.

### Setting up Wi-Fi

1. Make the secret (step 2 below) and put it in `.env` on both Pis.
2. Pick which robot listens (say Bob). Find his address: on the same Wi-Fi, `hostname -I` on his Pi, or a
   name such as `bobcena.local`; across houses use a **Tailscale** address (`tailscale ip -4`, a `100.x.x.x`
   number, or his Tailscale machine name). Both Pis need Tailscale signed in to the same account for that.
3. Bob, in `config.local.toml`:
   ```toml
   [radio]
   enabled = true
   transport = "wifi"
   role = "listen"
   ```
4. John, the other way round:
   ```toml
   [radio]
   enabled = true
   transport = "wifi"
   role = "connect"
   peer_address = "100.64.0.12"      # Bob's address or host name
   ```
5. Restart both. Bob's log says `Radio: waiting for John on Wi-Fi, port 8765`, then `Radio: linked with John`.

If John isn't Bob's Python code, give your friend the updated [JOHN_PROMPT.md](../JOHN_PROMPT.md): its radio
code now has the Wi-Fi option.

**Safety on the network.** The listener opens one TCP port (8765). Anyone who can reach it can connect, but
every message must be signed with the shared secret or it is dropped, and a connection that doesn't send a
valid hello within 10 seconds is cut off, so a stranger can't hog the only slot. Only one robot can be linked
at a time. To keep the port off networks you don't trust, set `bind` to one address (such as Bob's Tailscale
address) instead of `"0.0.0.0"`.

## Setting it up (once, on both robots)

### 1. Pair the two Pis (Bluetooth only; skip for Wi-Fi)

Pairing makes the Bluetooth link encrypted. On **both** Pis:
```bash
sudo systemctl enable --now bluetooth
```

Find Bob's address on Bob: `bluetoothctl show`, the line `Controller AA:BB:CC:DD:EE:FF`.

**On Bob**, run `bluetoothctl`, then type:
```
power on
agent on
default-agent
discoverable on
pairable on
```

**On John's Pi**, run `bluetoothctl`, then:
```
power on
agent on
default-agent
scan on
```
When Bob's address appears: `pair AA:BB:CC:DD:EE:FF`, confirm the code on both sides, then
`trust AA:BB:CC:DD:EE:FF`. Type `exit` to leave.

### 2. Make the shared secret

On one Pi:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```
Put the result in `.env` on **both** Pis:
```
BOB_RADIO_SECRET=<the text it printed>
```
Share it privately (in person, or a private message). **Never paste it into a chat with an AI**, or anywhere
public. Bob refuses to start the radio if it's missing or shorter than 16 characters.

### 3. Switch it on

On Bob, under `[radio]` in `config.toml`: `enabled = true`, keeping `role = "listen"`. John's settings use
`role = "connect"` and `peer_address = "<Bob's address>"`. Copy it over and restart Bob.

The log shows `Radio: waiting for John on channel 3`, then `Radio: linked with John` once John connects.

### 4. Give your friend the instructions

[JOHN_PROMPT.md](../JOHN_PROMPT.md) is a message for your friend to paste into their chat with Claude. It
contains the message format, test values to check their code against, the safety rules, and the complete
radio code, so John's radio will be compatible.

## Watching and controlling

| Command | Effect |
|---|---|
| `/radio` | link state, messages sent/received/rejected, and whether Claude may send |
| `/radio log 20` | the last 20 messages, with times and who sent them |
| `/radio say hello John` | send a message yourself |
| `/radio ai off` / `on` | stop or allow Claude sending (he's told the radio is off) |
| `/radio off` / `on` | drop the link / reconnect |

Every message also appears in the log as a green `RADIO Bob -> John: ...` line, and is saved to
`logs/radio.jsonl` on the Pi. The status bar shows `radio connected` (or `waiting`).

## Safety and cost

- **John can't control Bob.** His messages reach Claude as quoted, untrusted text. Claude is told John can't
  give orders, change his goal, or override you. Line breaks are removed from John's messages, so a message
  can't pretend to be "Operator says:". Nothing from the radio can move the wheels directly.
- **Two AIs could chat forever, and every message costs money.** Claude may send at most 6 messages a minute
  (`ai_max_per_minute`), is told to stop when the conversation is over, and stops at once with
  `/radio ai off`, `/pause` or `/estop`.
- **Floods are dropped.** Bob accepts at most 30 messages a minute from John, ignores repeated messages, and
  rejects anything unsigned or wrongly signed.

## Settings

Under `[radio]`:

| Setting | Bob's value | What it does |
|---|---|---|
| `enabled` | false | switch the radio on |
| `name` | `"Bob"` | this robot's name |
| `peer_name` | `"John"` | the other robot's name |
| `transport` | `"bluetooth"` | `"bluetooth"` or `"wifi"`. Both robots must use the same |
| `role` | `"listen"` | `"listen"` (wait) or `"connect"` (call). One robot must be each |
| `peer_address` | `""` | the other robot's Bluetooth address, or (Wi-Fi) its host name or IP address (needed for `"connect"`) |
| `channel` | 3 | Bluetooth only: both robots must use the same number |
| `port` | 8765 | Wi-Fi only: the TCP port; both robots must use the same number |
| `bind` | `"0.0.0.0"` | Wi-Fi only, for the listener: which address to listen on |
| `ai_max_per_minute` | 6 | how many messages Claude may send per minute |

The shared secret is `BOB_RADIO_SECRET` in `.env`.

## Troubleshooting

| Problem | Fix |
|---|---|
| `Radio disabled: set BOB_RADIO_SECRET` | add the secret (16+ characters) to `.env` on both robots |
| Wi-Fi: caller says `Connection refused` or times out | the listener isn't running yet, the address is wrong, a different `port`, or the robots can't reach each other (try `ping <address>`; with Tailscale check `tailscale status` on both) |
| Stuck at `waiting for John` | is John running and set to `connect` with Bob's address? Check pairing: `bluetoothctl devices` |
| `dropped a message that failed authentication` | the secrets differ, or John's name isn't "John": check both `.env` files and `peer_name` |
| Link keeps dropping | distance or interference: move them closer; Wi-Fi and Bluetooth share the antenna |
| Claude keeps chatting | `/radio ai off`, or lower `ai_max_per_minute` |
| It still doesn't link | paste the `Radio:` lines from the log into a chat for help |
