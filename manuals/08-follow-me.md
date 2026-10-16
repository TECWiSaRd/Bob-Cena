# Manual 08: Follow me

Bob can follow a person around: he turns to face them and keeps about a metre away.

> **Status:** the face detector was tested on real photos, and the steering was tested in a detailed
> simulation (he homed in smoothly, stopped at the right distance and never reversed). It **hasn't been
> tried on your real Bob yet**. Expect to tune the settings below.

---

## Starting and stopping

| How | Start | Stop |
|---|---|---|
| Console | `/follow` (30 s) or `/follow 20` | `/follow off` |
| Your voice (microphone on) | say "follow me" or "come here" | "stop" works only while he's standing still (see below) |
| Claude | uses his `follow_person` tool when someone asks him to follow | ends by itself |
| Dashboard | **Follow me** button | **Stop following** |

**Always** available: Space, `/estop`, `/pause` or the dashboard's emergency stop end a follow instantly.

**Don't rely on your voice to stop him.** The microphone is deliberately deaf while the wheels turn (motor
noise would be transcribed as nonsense), so while he's driving he probably won't hear "stop". Use the
console, the dashboard or a physical stop button.

## How it works

Claude only thinks every few seconds, which is far too slow to follow someone smoothly. So during a
follow, a small face detector on the Pi takes over the steering, about 8 times a second:

1. **Find a face.** The detector looks for faces in each picture. If several people are in view, he sticks
   with the one he was already following, otherwise picks the biggest (nearest).
2. **Turn toward it.** If the face is left of centre he turns left, right of centre he turns right. A small
   zone in the middle (`deadzone`) counts as "straight ahead", so he doesn't wobble.
3. **Keep his distance.** A face's size in the picture tells him roughly how far away the person is
   (an adult face is about 20 cm tall). Too small, he drives closer; the right size, he stops.
4. **If the person disappears**, he stays still briefly, then turns slowly toward where he last saw them.
   After `lost_after_s` (3 s) without a face, he stops and the follow ends.

When it ends, Claude is told how it went, for example: `followed for 14s (saw a face in 92% of checks);
ended: lost sight of the person (last seen on the left)`.

## Limits to know

- **He follows faces.** It works while the person is facing Bob. If they turn their back, he loses them.
  This is the biggest limitation.
- **Range is about 2 metres.** Further away, faces are too small to detect reliably.
- **He never reverses** to back away from someone. If you walk toward him, he just stops.
- **He won't close in on anything nearer than 40 cm** if the distance sensor is fitted.
- **Each steering command lasts only a fraction of a second.** If the follow program ever stalls, the
  wheels stop by themselves.
- The speed cap, obstacle reflex, `/motion off` and the emergency stop all still apply.
- **Following needs the camera on.** With `/camera off`, it refuses to start.

## Tuning

All under `[follow]` in `config.toml`:

| Setting | Default | What it does | Adjust if... |
|---|---|---|---|
| `distance_m` | 1.0 | how far from the person he tries to stay | he gets too close or hangs back |
| `max_speed` | 0.5 | top speed while following (the overall speed cap still applies) | he's too slow to keep up, or too eager |
| `max_seconds` | 60 | longest single follow | |
| `lost_after_s` | 3.0 | how long without a face before giving up | he gives up too soon / searches too long |
| `turn_gain` | 0.9 | how strongly he turns toward the person | **lower it if he swings left and right**; raise it if he turns sluggishly |
| `forward_gain` | 2.5 | how strongly he closes distance | lower it if he lurches forward |
| `deadzone` | 0.12 | how far off-centre counts as "straight ahead" (0 = centre, 1 = picture edge) | raise it if he wobbles |

Also important: **`fov_deg` under `[camera]`** must match your camera. Distance estimates depend on it.

## The face detector

`install.sh` downloads a small face-finding model called **YuNet** into `models/`. It copes with turned
heads and dim light. Without it, Bob falls back to OpenCV's older built-in detector, which mostly finds
faces looking straight at the camera. The log says which one is in use: `FOLLOW face detector: YuNet`.

## Troubleshooting

| Problem | Fix |
|---|---|
| `can't follow: no camera picture` | the camera is off or missing: `/camera on`, see [manual 07](07-camera-stream-and-dashboard.md) |
| `face detection isn't available` | install OpenCV: re-run `./install.sh` |
| `movement is disabled` | `/motion on` |
| He swings left and right | lower `turn_gain` (try 0.6) or raise `deadzone` |
| He stops too far away | lower `distance_m`, and check `fov_deg` |
| He loses you constantly | face him, keep within 2 m, improve the lighting; check the detector is YuNet |
| He doesn't move at all, but sees you | the speed may be below the motors' minimum: raise `/minduty` |
