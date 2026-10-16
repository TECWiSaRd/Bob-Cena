# Manual 06: Calibration

Bob can measure his own movement with his camera. Calibration answers two questions:

1. **How far does a spin really turn him?** So Claude can plan "turn 90 degrees" instead of guessing.
2. **Does he drift when driving straight?** So the drift can be cancelled with a trim.

> **Status:** tested in a detailed simulation (it measured turns within 0.3% and the drift fix within
> 0.001), but **not yet on your real Bob**. Real floors, wobbly bodies and real wheels are messier: run
> each calibration twice and check the results agree.

---

## Before you start

- **Pause Bob.** Calibration needs the wheels to itself and refuses to run while the AI is running:
  `/pause`.
- **The camera must be on** and seeing a room with some detail: furniture, pictures, a bookshelf. A blank
  wall or a plain floor gives it nothing to measure against.
- **Clear floor.** For turns, room around him. For straight, about a metre in front of him.
- **Set the speed cap you normally use.** Turn rates are measured at the current `/speed`. If you change
  the cap later, re-run the turn calibration (Claude is told when they no longer match).
- Keep a finger on **Space**. It stops calibration like it stops everything else.

## Measuring turns

```
/calibrate turn        explains what will happen; nothing moves yet
/calibrate turn go     starts
```

**What happens:** at three speeds (0.4, 0.7 and 1.0), Bob does a short test spin to the left, then a spin
sized to turn about 15 degrees. After each spin he spins back the same amount, so he ends up roughly where
he started. That's about six spins each way, taking a minute or so.

**How it measures:** before and after each spin he takes a picture and works out how far the view slid
sideways. Using the camera's field of view (`fov_deg`), that becomes degrees.

**Result:** the log says, for example:

```
CALIB done: turn rates (deg/s at command speed): 0.4: 39.9, 0.7: 75.2, 1: 110.2 - saved, and Bob has been told
```

So at speed 0.7, a 1-second spin turns him about 75 degrees: a 90-degree turn needs about 1.2 seconds. These
rates go into every status report Claude sees.

## Measuring straight-line drift

```
/calibrate straight go
```

**What happens:** Bob drives forward about half a metre at speed 0.6, then reverses back. He does this
twice: once as he is, and once with the right wheel nudged slightly faster. From how the view turned during
each run, he works out the trim that cancels the drift.

**Result:** the log says, for example:

```
CALIB done: drift +3.4 deg/s before; trims now left +0.000, right -0.076 - saved. Run /fwd 3 to check it
```

Check it worked: `/speed 0.6`, then `/fwd 3`. He should now go straight. If not, run it again, or fine-tune
by hand with `/trim` ([manual 05](05-driving-and-motors.md)).

## Other commands

| Command | Effect |
|---|---|
| `/calibrate show` | the saved turn rates and current trims |
| `/calibrate cancel` | stops a run in progress |

## Where results are saved

In `tuning.json` on the Pi, together with `/trim` and `/minduty`. They survive restarts and copying code
from your Mac. Delete `tuning.json` to start over.

## Getting good results

- **Set `fov_deg` correctly** under `[camera]`. Every measurement depends on it. Typical values: Pi Camera
  Module v2 about 62, Camera Module 3 about 66, most USB webcams 60-78 (check your camera's specifications).
  A wrong value makes every measured angle wrong by the same proportion.
- **Use a textured view** with things at different distances.
- **Nothing should move in view** while it runs: no people walking past, no pets.
- **Use fresh batteries.** Weak batteries make the motors slower, and the rates won't hold later.
- **Re-run after changes:** new batteries, a new floor surface, new wheels, a different speed cap.

## When it refuses or fails

Calibration never changes anything unless it got a clear measurement. Messages you might see:

| Message | Meaning | Fix |
|---|---|---|
| `pause Bob first` | the AI is running | `/pause` |
| `E-stop active` | the emergency stop is on | `/clear` |
| `calibration needs the camera` | the camera is off or missing | `/camera on` |
| `the scene doesn't have enough detail` | blank wall or plain view | point him at furniture |
| `the turn was too big to measure safely` | he turns very fast | lower `/speed` and try again |
| `Bob didn't turn left at speed 0.4` | a wheel is reversed, or too weak to move in a short burst | check `/left 0.5`; raise `/minduty` |
| `Bob was stopped early` | something blocked the straight run | clear the floor in front of him |
| `less than 80 cm of clear floor ahead` | the distance sensor sees something | clear the path |
| `the probe changed the drift by too little` | the measurement was too noisy to trust | try a more textured scene, and run it again |
