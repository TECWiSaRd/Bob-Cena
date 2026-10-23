# Manual 24: Sleep mode and going to a room

## Sleep mode

At night, or when you tell him, Bob rests. It also saves money, since an empty, dark room needs hardly any thinking.

While asleep he:
- **does not wander**: the AI's driving is refused ("it is sleep time"). You can still drive by hand, and the emergency stop works as always;
- **thinks rarely**: a routine look every 15 minutes, or sooner only if the picture changes a lot (lights on, a big movement);
- **is told to stay quiet** and to speak only if there's a real reason;
- **wakes when spoken to**: any message, spoken or typed, wakes him for 2 minutes, then he drifts off again.

```
/sleep on        rest now
/sleep off       wake up (stays awake whatever the time)
/sleep auto      follow the schedule
/sleep           show the state
```
A schedule, in `config.local.toml`:
```toml
[sleep]
enabled = true
start = "23:00"
end = "07:00"
```
The status bar shows `SLEEPING`, and the dashboard has Sleep and Wake up buttons. Settings: `wake_for_s` (120), `idle_max_s` (900),
`change_percent` (15). Sleep mode does not turn the microphone off: with the wake word on, he only reacts to "Hey Bob".

## Going to a room

With room tags (manual 19), Bob can drive to a room by following its tag:
```
/goto kitchen      go to the Kitchen
/goto stop         cancel (the emergency stop works too)
/goto              lists the rooms that have a tag
```
Claude has the same ability (the `go_to_room` tool) and uses it when someone asks him to go somewhere.

**How it works.** He turns to find the room's tag (the same slow turn as `/locate`), then moves forward a little at a time:
a short push, stop, look again, steer to keep the tag in the middle. He only moves forward right after seeing the tag, never
blind. He has arrived when the tag looks big enough (`tag_arrive_px`, 180 pixels). Arriving also tells him which room he is in,
so the lights work. It is slow on purpose (`goto_speed` 0.35, and the speed cap still applies).

**What he will not do.** He never goes round obstacles: if the distance sensor stops him, or the way is blocked, he stops and says
so. He gives up after `goto_seconds` (90) or after turning all the way round without seeing the tag. He refuses when the AI is
paused, the emergency stop is on, movement is off, or he's asleep.

**Rooms with more than one door.** A tag has to be visible from where he starts, which often isn't true from another room. For
that, give a route: the tags to reach in order, ending at the destination:
```toml
[home]
tags = { 1 = "Kitchen", 2 = "Living Room", 5 = "Hallway" }
paths = { Kitchen = [5, 1] }          # go to the hallway tag first, then the kitchen tag
```
Put a big tag at each doorway and one in the room itself. The route is only as good as where you stick the tags.

**Not tried on real hardware yet.** The logic is tested in a simulated flat; real driving depends on your floor, wheels and
camera, so first try it with the wheels off the ground, then in a clear room, watching the emergency stop.

| Problem | Fix |
|---|---|
| `I don't know a room called ...` | only rooms with a tag in `[home] tags` work; `/goto` lists them |
| `couldn't find tag N after turning all the way round` | the tag isn't visible from here: add a route, or start closer |
| `blocked: obstacle ...` | something is in the way; move it, or drive him round by hand |
| Stops short, or bumps the tag | tune `tag_arrive_px` (smaller = stops sooner) |
| Overshoots or wanders | lower `goto_speed` |
