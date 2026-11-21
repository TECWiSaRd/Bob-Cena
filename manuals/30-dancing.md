# Manual 30: Dancing

`/dance` makes Bob do a little dance: wiggles, spins and out-and-back steps, with beeps and chirps. He moves around a bit but stays **roughly where he is**:
every forward step is followed by the same step backward, every arc by its mirror image, and every spin by the opposite spin.

## Using it

| Command | What it does |
|---|---|
| `/dance` | the **party** dance (a bit of everything) for 30 seconds |
| `/dance wiggle` | quick left-right shimmies in place |
| `/dance spin` | a spin one way, then the other |
| `/dance steps` | small steps forward and back, and two curved ones |
| `/dance party 60` | any dance for that many seconds (3 to 300) |
| `/dance off` | stop (or `/stop`, `/estop`, saying "stop") |

The AI is paused while he dances (it stays paused until `/resume`), so his own moves never fight the dance.

**What ends it:** the time running out, `/dance off`, `/stop`, saying "stop", the emergency stop, `/pause`, `/motion off`, `/resume`, `/drive` or the joystick, or an error.
When the time runs out he finishes the step he is in first, so he never ends up half-way through a move (that can take up to about two seconds more).

**Safety:** every wheel command lasts a second or less, so if Bob's program died he would stop by himself. The speed cap, the emergency stop and the distance sensor apply
as for any other driving. If the sensor sees something close ahead, he **skips that step** completely (the out and the back), and keeps dancing with the rest.
Claude has no tool to start a dance.

**Space:** the moves are small, but give him about half a metre all round, and keep cables and things on the floor out of the way. The steps are timed, not measured,
so on a slippery or thick-carpet floor he will drift a little over a long dance. Try it first with the wheels lifted.

## Settings (`[dance]` in `config.local.toml`)

| Setting | Meaning | Default |
|---|---|---|
| `enabled` | the `/dance` command | `true` |
| `speed` | how fast the moves are (the `/speed` cap still applies on top) | `0.5` |
| `default_seconds` | how long a dance lasts when you don't say | `30` |
| `max_seconds` | the longest a dance may last | `300` |
| `sounds` | beeps and chirps along with the moves | `true` |

## Not verified on a real robot

It is tested with pretend wheels and a pretend clock (they check that every dance ends where it started, that the time limit never cuts a step in half, and that every
override stops it). How it looks and feels on your floor is for you to judge: if it is too wild, lower `speed`, or use `/dance wiggle`, which hardly moves him at all.
