# Manual 26: Face recognition

Bob can learn to recognise people who **ask** to be remembered, and tell Claude their names when they are in view. It is off
until you switch it on.

> **Status:** tested with simulated faces and the real model files loading on a Mac. **Not tried on a real Pi camera or
> with real faces yet.** Expect mistakes, especially in poor light, at an angle, and between similar-looking faces.

---

## The rules Bob follows

- **He only learns a face when someone with permission asks** (`/face remember NAME`, then a second step to confirm), and the
  person being remembered should agree. He never enrols anyone by himself.
- **A face he doesn't know is never stored.** He just doesn't recognise it.
- **Only numbers are kept, never a photo.** Each sample is a list of 128 numbers describing the face. They are in `faces.json`
  on the Pi, readable only by Bob's account, and are never sent to Claude or anywhere else. Claude is told a **name** only
  when a stored face matches.
- **He gets better only when a person confirms** who it is (`/face improve NAME`).
- **Anyone can be erased** at any time: `/face forget NAME`, or `/face forget all`.
- **Claude cannot do any of this.** He has no tool to learn or forget a face. If someone asks him to remember their face, he tells
  them to ask an operator.

## Setting it up

1. Run `./install.sh` on the Pi. It downloads the face-recognition model (about 37 MB) into `models/`, next to the face finder.
2. In `config.local.toml`:
   ```toml
   [faces]
   enabled = true
   ```
   Or try it without editing: `/face on` (lasts until Bob restarts).
3. Restart Bob. `/face` says whether it works. If the model is missing it says so and Bob carries on without it.

## Introducing someone

1. The person stands alone in front of Bob, facing the camera, in good light.
2. An owner or operator types `/face remember Sam`. Bob explains what he will do.
3. If Sam agrees, type `/face remember confirm` within 30 seconds (the same person who typed the first command). Bob takes
   5 pictures over a few seconds and keeps only the numbers. If he sees more than one face, or none, he saves nothing and says why.
4. `/face` lists who he knows and how many samples each has.

## Making it better

Matching improves with samples in different light and angles. When someone he **does** know is in front of him, and he got it
wrong or didn't recognise them, wait a second, then type `/face improve Sam`. He adds the face he just saw to Sam's samples
(at most 8 per person; when full, the new one replaces the stored one it most resembles, so what he keeps stays varied).
He needs to see exactly one face, within the last 30 seconds.

## What Claude sees

When a stored face is in view, the status report gets a line like:

`People I recognise in view (a guess, can be wrong): Sam. 1 other face I don't recognise.`

Claude is told it is a guess and not to claim to recognise anyone who isn't in that line. When nobody is enrolled, Bob doesn't
even run the recognition.

## Commands

| Command | What it does | Who |
|---|---|---|
| `/face` | who he knows (and whether it is on) | owner, operators |
| `/face on`, `/face off` | switch it on or off until restart | owner, operators |
| `/face remember NAME` then `/face remember confirm` | introduce someone (two steps, same person) | owner, operators |
| `/face remember cancel` | cancel the first step | the same person |
| `/face improve NAME` | add the face he just saw to NAME | owner, operators |
| `/face forget NAME` or `/face forget all` | erase one person or everybody | owner, operators |

Viewers, dashboard guests and app devices can't use `/face`.

## Settings

Under `[faces]`:

| Setting | Default | What it does |
|---|---|---|
| `enabled` | false | switch recognition on |
| `match_threshold` | 0.40 | how alike two faces must be to count as the same person. Higher = fewer wrong names but more "don't know" |
| `margin` | 0.05 | the best match must beat the next person by this much, so lookalikes give "don't know" |
| `samples_to_take` | 5 | pictures taken when someone is introduced |
| `confirm_seconds` | 30 | time to type `/face remember confirm` |
| `max_people` | 20 | how many people he can know |
| `max_samples` | 8 | samples per person |

## Privacy notes

- If Bob visits houses with people who haven't agreed to be recognised, leave it off or only introduce people who agree.
  Some places have laws about face data; the numbers kept here count as face data.
- `faces.json` is excluded from git and from `deploy.sh`, so it stays on the Pi it was made on. Back it up like `people.json`.
- Deleting `faces.json` erases everyone.

## Troubleshooting

| Problem | Fix |
|---|---|
| `/face` says "unavailable: ... model files" | run `./install.sh` again, or check `models/face_recognition_sface_2021dec.onnx` exists |
| "I couldn't see a face clearly" | face the camera, more light, closer (about 1 m) |
| "I could see more than one face" | only the person being introduced in front of him |
| Calls the wrong person | `/face improve` the right person when they are in view, raise `match_threshold`, or `/face forget` and introduce again in better light |
| Never recognises someone | introduce them again in the light they are usually in, then `/face improve` a few times |
