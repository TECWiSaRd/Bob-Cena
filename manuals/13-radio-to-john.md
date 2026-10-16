# Manual 13: Radio to John

Bob can talk to **John**, your friend's robot, over Bluetooth. Claude sends John short messages and reads
his replies, and you can watch the whole conversation.

> **Status:** the message format, signing and connection logic were tested here with two simulated robots
> talking over an ordinary network connection. **The real Bluetooth link hasn't been tried yet**, and it's
> switched off until both robots are set up.

---

## How it works

- **The link.** Bob waits for a connection (`role = "listen"`) and John connects to him (`role =
  "connect"`), using Bob's Bluetooth address. If the link drops, it reconnects by itself.
- **Signed messages.** Both robots share a secret password (`BOB_RADIO_SECRET`). Every message is signed
  with it, so Bob ignores anything from a stranger, even one who manages to connect.
- **Claude's side.** Bob has a `radio_send` tool. John's messages appear in Bob's next status report, under
  "Messages from John", as quoted text.

## Setting it up (once, on both robots)

### 1. Pair the two Pis

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
| `role` | `"listen"` | `"listen"` (wait) or `"connect"` (call). One robot must be each |
| `peer_address` | `""` | the other robot's Bluetooth address (needed for `"connect"`) |
| `channel` | 3 | the Bluetooth channel: both robots must use the same number |
| `ai_max_per_minute` | 6 | how many messages Claude may send per minute |

The shared secret is `BOB_RADIO_SECRET` in `.env`.

## Troubleshooting

| Problem | Fix |
|---|---|
| `Radio disabled: set BOB_RADIO_SECRET` | add the secret (16+ characters) to `.env` on both robots |
| Stuck at `waiting for John` | is John running and set to `connect` with Bob's address? Check pairing: `bluetoothctl devices` |
| `dropped a message that failed authentication` | the secrets differ, or John's name isn't "John": check both `.env` files and `peer_name` |
| Link keeps dropping | distance or interference: move them closer; Wi-Fi and Bluetooth share the antenna |
| Claude keeps chatting | `/radio ai off`, or lower `ai_max_per_minute` |
| It still doesn't link | paste the `Radio:` lines from the log into a chat for help |
