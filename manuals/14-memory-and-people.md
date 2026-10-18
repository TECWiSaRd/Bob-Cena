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

## The event timeline (for reviewing what happened)

This isn't memory Bob uses. It's a record **for you**, so you can see afterwards what he saw, decided and
did: useful for tuning, and for working out what went wrong after an incident. It's **off by default**.

Turn it on with `/timeline on` (or `enabled = true` under `[timeline]`). While on, it writes:
- **`logs/timeline/YYYY-MM-DD.jsonl`**: one line per event. `tick` (a thinking round, with the distance
  reading), `tool` (what Claude asked for, the result, and why a move stopped), `operator` (messages and `/ask`),
  `operator_command` (every other `/command` you or the dashboard run: `/pause`, `/motion off`, `/speed`, `/fwd`,
  `/find` and so on), `manual_move` (the start of each burst of hand-driving with the keys or the dashboard pad),
  `stop` (the obstacle reflex), `estop` (an emergency stop and its source).
- **`logs/timeline/thumbs/`**: small pictures, at most one every 10 s, named by time. Each `tick` line
  names the matching picture.

| Command | Effect |
|---|---|
| `/timeline` | status: events recorded, space used, how long it's kept |
| `/timeline show 20` | the last 20 events |
| `/timeline on` / `off` | start or stop recording (existing records stay) |
| `/timeline clear` | **deletes every record and picture** |

Records older than `keep_days` (7) are deleted automatically, and the folder never grows past `max_mb`
(200). Everything stays on the Pi. To copy it to your computer:
`rsync -av adam@bob:~/bob/logs/timeline/ ~/Desktop/bob-timeline/`.

**Privacy:** the pictures can show people and your home. Tell people nearby, set `thumbnails = false` if
you only want the text record, and use `/timeline clear` when you're done. `/people clear` does not delete
timeline pictures.

## Searching everything: the index

As the timeline and notes grow, scrolling gets slow. Bob keeps a **search index** (`logs/index.db`, one
SQLite file) so you can find things in seconds. The index is only a *copy* made for searching. The real
records stay in their own files, and if the index is ever damaged Bob deletes it and builds it again by himself.

**What's in it**

| Source (`source:`) | What | Kept |
|---|---|---|
| `timeline` | the event timeline | as long as the timeline files exist |
| `note` | Bob's notes | follows `memory.json` |
| `person` | people he knows | follows `people.json` |
| `radio` | messages with John | `[index] keep_days` (30) |
| `log` | WARNING and ERROR lines from the log | `[index] keep_days` (30) |
| `manual` | these manuals and the README | follows the files |

**Searching** (from the console, not the dashboard):

```
/search lens covered
/search kind:estop since:yesterday
/search calibrate source:manual
/search red cap source:person
```

- Every word you type must match (as the start of a word, and plural/singular forms match: "cover" finds
  "covered").
- Filters: `kind:` (an event type such as `estop`, `tool`, `tick`, `operator_command`), `source:` (the table
  above), `since:` (`30m`, `2h`, `3d`, `today`, `yesterday`, or `2026-10-16`).
- Up to 20 results, newest at the bottom. Hits with a camera picture show its file name, in
  `logs/timeline/thumbs/` (`[picture deleted]` if the cleanup already removed it).
- With no words, `/search kind:estop` just lists the latest of that kind.

**Keeping up:** a background thread reads only what's *new* in each file, every 5 seconds, so it stays fast
however big the history gets. Nothing slows Bob's thinking.

**Privacy:** the index follows the records it copies. When the timeline deletes an old day, those rows go too.
`/timeline clear` removes them immediately. `/forget` and `/people forget` or `clear` update the index within
moments. A damaged or unwanted index can be deleted with `/index rebuild` (or by removing `logs/index.db`).

**Letting Claude search too (off by default).** With `/index ai on` (or `[index] ai = true`), Claude gets a
`recall` tool for his own past: *what happened last time I went down the hallway?* It can search only the
**timeline and radio** records (not the log or manuals, and notes and people are already in every status
report). He gets at most five short lines, which are marked as old data and never as instructions. `/index ai
off` takes it away again. Turn it on only if you're comfortable with timeline text (including words he heard)
coming back into his prompts.

| Command | Effect |
|---|---|
| `/search WORDS [kind:x] [source:x] [since:x]` | search |
| `/index` | what's indexed, its size, and when it last updated |
| `/index sync` | update it now |
| `/index rebuild` | delete it and build it again from the files |
| `/index ai on` / `off` | allow or forbid Claude's `recall` tool |

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
| `logs/timeline/` | the event timeline, if turned on | yes |
| `logs/index.db` (and `-wal`, `-shm`) | the search index | yes: Bob rebuilds it |
| `music_duck.json` | the music volume if Bob crashed while ducking | appears and disappears by itself |
| `wakeword_clips/` | your recordings from `wakeword_tools.py` | yes |

## Troubleshooting

| Problem | Fix |
|---|---|
| Bob behaves oddly cautiously or fixated | read `/notes`: an old note may be steering him. `/forget` |
| Bob forgot a conversation | recent conversation resets when Bob restarts; only notes and people last |
| He calls someone by the wrong name | correct him out loud; or `/people forget <name>` |
| Log: `memory.json is damaged` | a power cut corrupted it. Bob started with no notes and kept the old file as `memory.json.bad` |
| `/search` finds nothing you expect | `/index` shows what's in it. `/index rebuild` builds it again. The timeline only has records if it was on (`/timeline`) |
| `/search` says `I don't understand since:...` | use `30m`, `2h`, `3d`, `today`, `yesterday` or `2026-10-16` |
| Log: `search index damaged ... rebuilding it` | harmless: it was deleted and rebuilt from the real files |
| `/people` says nobody yet | he only saves people when they introduce themselves |
