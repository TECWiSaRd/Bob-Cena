# Manual 14: Memory and people

Every tick, Claude starts fresh. So how does Bob remember anything? This manual explains his four kinds of
memory, where each is stored, and how to see or wipe them.

---

## Bob's four memories

| Memory | What it holds | How long it lasts | Where |
|---|---|---|---|
| **Recent actions** | his last 15 actions and their results | until Bob restarts | in the program |
| **Recent conversation** | the last 12 lines said by you, Bob, people he heard, and John | until Bob restarts | in the program |
| **Notes** | things he chose to remember, up to 40 | **permanently** | `memory.json` on the Pi |
| **People** | names, how to recognise them, notes, up to 30 | **permanently** | `people.json` on the Pi |

All four are included in the status report Claude reads every tick.

---

## Notes

Claude saves notes with his `remember` tool. He's encouraged to note useful things: how far a spin
actually turns him, landmarks, people's names, and progress on his goal.

- Up to 40 notes. When full, the oldest is dropped.
- Each note is at most 300 characters.
- Notes appear in the log as green `NOTE ...` lines when he saves them.

| Command | Effect |
|---|---|
| `/notes` | shows all his notes |
| `/forget` | **deletes all of them** (there's no undo) |

**Wipe stale notes.** Notes can outlive the situation that caused them. For example, when the camera was
missing, Bob saved "Don't drive while blind". Once the camera worked, that note would have kept him overly
cautious. After fixing a problem, check `/notes` and `/forget` if needed.

---

## People

Claude saves people with his `remember_person` tool: a **name**, **how to recognise them** (hair, clothes,
glasses, height, voice), and **notes** (what they like, what they asked for). Calling it again with the same
name updates that person. Bob also records when he last saw them.

The list appears in his status report as, for example:
```
People you know (how to recognise them; greet people you recognise by name):
  - Sam: tall, red cap, glasses | notes: likes robots (last seen 2026-10-14 18:45)
```

**Rules Claude is given:**
- Use only names people tell him.
- Don't guess identities from appearance alone: say he *thinks* he recognises someone, and check.
- Don't save sensitive details about anyone.

**Limits:** 30 people; when full, the person not seen for longest is dropped. Descriptions are at most 200
characters and notes 300. Recognition is Claude looking at the picture and comparing it to the descriptions,
so it's a friendly guess, not face recognition.

| Command | Effect |
|---|---|
| `/people` | lists everyone Bob knows |
| `/people forget Sam` | forgets one person |
| `/people clear` | forgets everyone |

---

## Privacy

- The notes and people files exist **only on the Pi**. Copying code from your Mac never overwrites them.
- But their contents are **sent to Claude with every tick**, as part of the status report.
- Tell people Bob may remember their name and what they look like, and use `/people forget` if anyone asks.

## Backing up and restoring

From your Mac:
```bash
rsync -av adam@bob:~/bob/{memory.json,people.json} ~/Documents/bob-backup/     # back up
rsync -av ~/Documents/bob-backup/{memory.json,people.json} adam@bob:~/bob/     # restore
```
Restart Bob after restoring.

## Other things Bob keeps on the Pi

| File | Holds | Safe to delete? |
|---|---|---|
| `tuning.json` | `/trim`, `/minduty`, calibration results | yes: you'll lose the tuning |
| `logs/bob.log` | the full log (2 MB per file; the current file plus 5 older ones are kept) | yes |
| `logs/radio.jsonl` | every radio message | yes |
| `captures/` | photos from `/snap` | yes |
| `music_duck.json` | the music volume if Bob crashed while ducking | appears and disappears by itself |
| `wakeword_clips/` | your recordings from `wakeword_tools.py` | yes |

## Troubleshooting

| Problem | Fix |
|---|---|
| Bob behaves oddly cautiously or fixated | read `/notes`: an old note may be steering him. `/forget` |
| Bob forgot a conversation | recent conversation resets when Bob restarts; only notes and people last |
| He calls someone by the wrong name | correct him out loud; or `/people forget <name>` |
| Log: `memory.json is damaged` | a power cut corrupted it. Bob started with no notes and kept the old file as `memory.json.bad` |
| `/people` says nobody yet | he only saves people when they introduce themselves |
