# Manual 10: Voice and sounds

Bob talks with a natural-sounding voice generated on the Pi itself, and plays little sound effects to
express himself. This manual covers both, and how to fix them.

> **Status:** confirmed on your Pi. Piper speech starts about 1.1 seconds after Bob decides to speak.

---

## How Bob speaks

1. Claude decides what to say (his `speak` tool), or you type `/say <text>`.
2. **Piper**, a text-to-speech program running on the Pi, turns the words into audio. Nothing is sent to
   the internet for this.
3. The audio plays through the speaker.

To start talking sooner, Bob splits what he says into sentences. The first sentence plays while the next
is still being generated. He also loads the voice once at startup and does a short warm-up, so even his
first sentence is quick.

**If Piper isn't installed or fails**, Bob automatically falls back to **espeak-ng**, an older, more
robotic voice. The log says which one he's using: `Speech engine: piper`.

### Every time Bob speaks

- It appears in the log as a cyan `SAY` line.
- The log also shows the timing: `Spoke with piper: first audio after 1.1s, done in 4.5s`. "Done" includes
  the time spent playing it, so long sentences take longer.
- The microphone stops listening while he speaks, and for a second afterwards, so he doesn't hear himself.
- Any music playing is turned down while he speaks, then back up ([manual 12](12-sound-system.md)).

## Sound effects

Bob's sounds are short tone patterns, made on the Pi when he first starts and saved in `sounds/`.

| Name | Sounds like | Used for |
|---|---|---|
| `startup` | four rising notes | Bob starting up |
| `beep` | one short beep | general signal |
| `chirp` | three quick rising notes | acknowledging, and "I'm listening" after a wake word |
| `happy` | a cheerful rising arpeggio | pleasure |
| `sad` | three falling notes | disappointment |
| `question` | two notes going up | curiosity |
| `alert` | three sharp high beeps | warning |

Claude can play them with his `play_sound` tool. You can play one with `/sound happy`.

## Commands

| Command | Effect |
|---|---|
| `/say <text>` | Bob says it |
| `/sound <name>` | plays a sound effect |
| `/mute` | silences all speech and sounds. Bob's words still appear in the log, and Claude is told he's muted |
| `/unmute` | sound back on |

## Choosing a voice

Bob uses `en_US-lessac-medium` by default. Piper has many voices:

```bash
cd ~/bob
.venv/bin/python -m piper.download_voices                                # list them
.venv/bin/python -m piper.download_voices --data-dir voices en_US-amy-medium   # download one
```

Then set `piper_model = "en_US-amy-medium"` under `[audio]` in `config.toml`, copy it over, and restart.

**Faster speech:** "low" voices (for example `en_US-lessac-low`) are quicker to generate but sound a little
rougher. If the first word takes more than a second or two, or there are gaps between sentences, try one.
Switching off the camera stream and the microphone also frees the Pi's processor.

## Volume

Bob has no speech-volume setting of his own: he uses the Pi's volume.

- **Without the music system:** `alsamixer` on the Pi (arrow keys to adjust, Esc to leave).
- **With the music system (PipeWire):** `wpctl set-volume @DEFAULT_AUDIO_SINK@ 70%`, or `wpctl status` to see
  outputs.

## Where the sound comes out

| Setting (`[audio]`) | Default | What it does |
|---|---|---|
| `tts` | `"piper"` | `"piper"` or `"espeak-ng"` |
| `piper_model` | `"en_US-lessac-medium"` | Piper voice name (in `voices/`) or a path to a `.onnx` voice file |
| `voice` | `"en-us"` | the espeak-ng voice (fallback only) |
| `speed_wpm` | 165 | espeak-ng speaking speed (fallback only) |
| `device` | `""` | the sound output for `aplay`. Empty means the Pi's default |
| `player` | `"auto"` | `"auto"` uses `pw-play` when PipeWire is running (needed to mix with music), otherwise `aplay` |

## Troubleshooting

**First, check the speaker itself works** (it should say "front left, front right"):

```bash
speaker-test -t wav -c 2 -l 1
```

| Problem | Fix |
|---|---|
| `speaker-test` is silent | wrong output: `sudo raspi-config` → System Options → Audio, or `aplay -l` and set `[audio] device` |
| `speaker-test` works, Bob is silent | is he muted (status bar says `audio MUTED`)? `/unmute` |
| Log says `aplay not found - audio simulated` | `sudo apt-get install alsa-utils` |
| Log says `No TTS engine found` | `sudo apt-get install espeak-ng`, and see Piper below |
| Log says `Piper not installed` | `.venv/bin/pip install piper-tts` |
| Log says `Piper voice ... not found` | run the download command the log shows |
| Robotic voice | Bob fell back to espeak-ng: check the log for why Piper isn't used |
| Speech is slow to start | try a "low" voice; free up CPU |
| Very quiet | raise the volume with `alsamixer` or `wpctl`; try powered speakers |
| `device busy` after installing the music system | set `player = "auto"` (the default) so speech goes through PipeWire |
