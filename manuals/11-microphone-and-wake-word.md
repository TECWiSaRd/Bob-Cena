# Manual 11: Microphone and wake word

With a USB microphone, you can talk to Bob out loud. He turns your speech into text on the Pi, then
answers like he would a typed message. A **wake word** ("Hey Bob") tells him you're talking to him.

> **Status:** confirmed on your Pi with your USB microphone (card "USB PnP Sound Device") and your
> "hey bob" wake word model. That model hears "Hey Bob" very reliably but also wakes to look-alikes such
> as "Hey Rob". See "Your wake word" below.

---

## Quick start

1. **Find the microphone** on the Pi:
   ```bash
   arecord -l
   ```
   Yours shows as `card 4: Device [USB PnP Sound Device]`. Bob's setting is already
   `device = "plughw:CARD=Device,DEV=0"` under `[mic]`. This name form still works if the card number
   changes after a reboot.
2. **Check it hears you** (speak during the 3 seconds; you should hear yourself back):
   ```bash
   arecord -D plughw:CARD=Device,DEV=0 -d 3 -f S16_LE -r 16000 -c 1 /tmp/test.wav && aplay /tmp/test.wav
   ```
   Silent or faint? Run `alsamixer -c 4`, press **F4** for the capture controls, make sure the mic isn't
   muted (`MM` means muted; press `M`), and set the level to about 70-80%.
3. **In Bob's console:** `/listen on`. The status bar shows `mic hands-free (...)`.
4. **Talk:** "Hey Bob, what do you see?" The log shows `WAKE heard 'hey bob'`, then `HEARD what do you
   see?`, and Bob answers.

The microphone is **off when Bob starts**, unless you set `enabled = true` under `[mic]`.

---

## How it works

```
 microphone ──► wake word listener ──► (woken) cut speech into sentences ──► Whisper turns it into text
                 (tiny audio model)                                                   │
                                                          "HEARD ..." in the log ◄────┘──► Claude answers
```

- **Wake word listener.** A tiny audio model (openWakeWord) listens only for the wake word. Nothing is
  transcribed until it hears it.
- **Listening window.** Once woken, Bob listens for 20 seconds (`wake_window_s`) without needing the wake
  word again. Every answer he gives restarts the window, so you can have a conversation.
- **Whisper** (the `tiny.en` model) turns your sentence into text, on the Pi. Only that text goes to Claude.
  Audio never leaves the Pi.
- If you say the wake word on its own, Bob chirps to show he's listening.

### When the microphone is deaf (on purpose)

| When | Why |
|---|---|
| while Bob is speaking, and 1 s after (`after_speech_s`) | so he doesn't answer himself |
| while the wheels are turning (`pause_while_driving`) | motor noise becomes nonsense text |
| while music is playing (`mic_deaf_while_playing`) | lyrics would be transcribed |
| after `/listen off` | off is off: nothing is recorded |

**So don't rely on your voice to stop a moving robot.** Use Space, the dashboard or a physical button.

---

## Two ways to listen

| Mode | How you use it | Good for |
|---|---|---|
| **hands-free** (default) | just talk, starting with the wake word | normal use |
| **push-to-talk** | press **Tab** (or type `/talk`) to start recording, press again to send | noisy rooms, privacy, when the wake word misbehaves |

Switch with `/listen mode ptt` or `/listen mode hands-free` (until restart), or `mode` under `[mic]`.
Push-to-talk never needs a wake word, and Bob answers straight away even if he's paused.

## Spoken commands

A few short phrases are handled instantly by Bob himself, without asking Claude. Only an utterance that is
**exactly** one of these counts, so normal sentences never trigger them:

| Say | Bob does |
|---|---|
| "follow me", "come here", "come with me", "come to me", "follow" | starts following you ([manual 08](08-follow-me.md)) |
| "stop", "halt", "freeze", "stay", "stay there", "stop following", "stop it" | stops the wheels, stops following, and pauses the AI |

"Please", "Bob" and "now" are ignored, so "Bob, stop now" works too.

---

## Your wake word

Bob's current setting is your downloaded **"hey bob"** model (`wake_model = "wakewords/hey_bob.onnx"`). When
we tested it with your own voice:

| You said | Result |
|---|---|
| "hey bob" (6 different ways) | all heard (scores 0.99-1.00) |
| "hey rob", "hey bobby", "hey boss", "hey mom", "hey bud/bill/ben" | **also woke him** (scores 0.72-1.00) |
| ordinary sentences, room noise | ignored (0.00) |

So it's very sensitive to "hey + a short name". To reduce false wakes, `wake_confirm = true` is switched on:
after the wake word fires, Bob checks the transcript actually contains "Bob" (loosely, so "Bub" and "Bop"
count, "Rob" and "Boss" don't). It catches most look-alikes, but "Hey Rob" still gets through, because
Whisper often hears "Rob" as "Bob". You decided that's acceptable for now.

**Options if it bothers you:**
- Raise the bar: `/listen wake threshold 0.7`.
- Use the reliable pretrained word: `wake_model = "hey_jarvis"` (and say "Hey Jarvis").
- Use push-to-talk.
- Train a better model: see [TRAINING_HEY_BOB.md](../TRAINING_HEY_BOB.md).

### Measuring a wake word model on your own voice

`wakeword_tools.py` records your voice and scores any model:

```bash
cd ~/bob
.venv/bin/python wakeword_tools.py record --device plughw:CARD=Device,DEV=0
.venv/bin/python wakeword_tools.py score wakeword_clips/positive/*.wav wakeword_clips/negative/*.wav
```

It asks you to say "hey bob" six ways, then look-alikes and normal speech, then records room noise. Scores
above 0.5 wake Bob. You want every "hey bob" above 0.5 and everything else below. To compare models, change
`wake_model` and score the same clips again.

---

## Commands

| Command | Effect |
|---|---|
| `/listen on` / `off` (or `/mic`) | start or stop the microphone |
| `/listen` | status and the live loudness level |
| `/listen mode ptt` / `hands-free` | change mode |
| `/listen threshold 0.03` | how loud counts as speech (0.002-0.5) |
| `/talk` or **Tab** | push-to-talk: start, then send |
| `/listen wake` | wake word status: which word, asleep or awake, the window |
| `/listen wake threshold 0.6` | how sure the wake word model must be (0.05-0.99) |
| `/listen wake window 20` | how long he keeps listening after waking (1-120 s) |
| `/listen wake sleep` | closes the listening window now (handy for testing one phrase at a time) |
| `/listen wake oww` / `text` / `off` | wake word engine: the audio model, matching "bob" in the transcript, or none (hear everything) |

## Settings

Under `[mic]`. Details in the [settings reference](15-settings-reference.md).

| Setting | Your value | What it does |
|---|---|---|
| `enabled` | false | start listening when Bob starts |
| `mode` | `"hands-free"` | or `"push-to-talk"` |
| `device` | `"plughw:CARD=Device,DEV=0"` | which microphone |
| `model` | `"tiny.en"` | Whisper model: `"base.en"` is more accurate but 2-3× slower |
| `threshold` | 0.02 | loudness that counts as speech |
| `silence_ms` | 800 | this much quiet ends a sentence |
| `max_seconds` | 15 | longest single recording |
| `after_speech_s` | 1.0 | deaf this long after Bob speaks |
| `pause_while_driving` | true | deaf while the wheels turn |
| `cpu_threads` | 3 | processor cores Whisper may use |
| `wake_engine` | `"openwakeword"` | `"openwakeword"`, `"text"` or `"off"` |
| `wake_model` | `"wakewords/hey_bob.onnx"` | the wake word model |
| `wake_threshold` | 0.5 | wake word sensitivity |
| `wake_confirm` | true | double-check the name in the transcript |
| `wake_word` | `"bob"` | the word for the `"text"` engine (also the name used by the two settings below) |
| `name_aliases` | `["mom", "bub", ...]` | words the speech model mishears as the name. When one **opens** what you said (after any "hey"), it is changed back to "Bob". "Mom's coming" or "my mom" are left alone |
| `initial_prompt` | `""` | a hint that helps the speech model hear the name. Empty = "The speaker is talking to a robot named Bob." |
| `wake_window_s` | 20 | listening window after waking |
| `wake_verifier` | `""` | experimental voice filter (see TRAINING_HEY_BOB.md) |

## When he is slow to answer after you speak

The wait after you stop talking has four parts, and the log now times two of them:

| Part | Typical | What controls it |
|---|---|---|
| 1. Waiting to be sure you finished | 0.8 s | `silence_ms` under `[mic]`. Try 500-600 for a quicker cut-off (too low cuts you off mid-sentence) |
| 2. Turning your voice into text | 1-3 s | the log line `Transcribed 2.1s of speech in 1.4s`. `tiny.en` is the fastest model; `base.en` is 2-3 times slower. The model now loads when the mic is switched on, so the first sentence isn't slow |
| 3. Claude thinking | 2-6 s | the log line `Claude replied in 3.2s`. `/model sonnet` or `/model haiku` is faster than Opus; `/effort low` helps; each tick sends a camera picture |
| 4. Speaking the answer | 1 s+ | Piper makes the first sentence while the rest is generated |

Read the two log lines after you speak to see which part is slow. If part 1 plus 2 is long, tune the microphone; if
`Claude replied in` is long, that is the model. Bob must also be un-paused (`/resume`) to answer spoken words in
hands-free mode.

## When he hears "Mom" instead of "Bob"

The small speech model (`tiny.en`) often turns "Bob" into "Mom", "Bub" or "Bop". Three things help, cheapest first:

1. **Already built in:** a hint tells the model the speaker is talking to a robot named Bob, and if what you said
   *opens* with a known mishearing (`name_aliases`), it is changed back to "Bob" before Claude sees it.
2. **A better model:** `model = "base.en"` under `[mic]` is noticeably more accurate. It is 2-3 times slower to
   transcribe, but still fine on a Pi 4 for short sentences.
3. **Speak clearly:** "Bob" is short and starts and ends with the same sound, which is hard for the small model.
   "Hey Bob," with a tiny pause, works better than "Bob" alone.

If it mishears the name as another word, add that word to `name_aliases`.

## Privacy

- The microphone records only after `/listen on`, and only to find the wake word and your sentence.
- Only the **text** of what you said goes to Claude, not audio.
- Transcripts appear in the log (`HEARD ...`) and the recent-conversation part of Bob's status report.
- A false wake means up to 20 seconds of nearby talk could be transcribed and sent. If that matters, use
  push-to-talk.

## Troubleshooting

| Problem | Fix |
|---|---|
| `audio open error: No such file or directory` | the device name is wrong: check `arecord -l` and `[mic] device` |
| `Giving up on the microphone` | after three failures Bob stops trying: fix the cause, then `/listen on` |
| `openWakeWord is missing or too old` | `.venv/bin/pip install --no-deps --upgrade 'openwakeword>=0.6'` |
| `faster-whisper isn't installed` | `.venv/bin/pip install faster-whisper` |
| He only reacts to the first "Hey Bob" | the 20 s window is open, so later wake words aren't logged. Use `/listen wake sleep` between tests |
| He wakes to "Hey Rob" etc. | see "Your wake word" above |
| He mishears names | Whisper `tiny.en` is fast but not perfect: try `model = "base.en"` |
| `HEARD` shows things nobody said | background noise: raise `/listen threshold` |
| He never hears you | `/listen` shows the level: speak and check it rises above the threshold |
| `device busy` after installing the music system | set `device = "pipewire"` |
| He ignores you while music plays | that's deliberate (`mic_deaf_while_playing`): use push-to-talk or pause the music |
