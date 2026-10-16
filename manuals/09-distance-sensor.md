# Manual 09: Distance sensor (HC-SR04)

An ultrasonic distance sensor gives Bob a reflex: the wheels refuse to drive into anything close in front of
him, **whatever Claude decided**. It works like a bat: it sends out a click too high to hear and times the
echo.

> **Status:** optional, and **not fitted yet** (it's waiting for resistors). The code was tested with a
> simulated sensor. Bob works normally without it.

---

## What it does

| Situation | Bob's reaction |
|---|---|
| Something closer than 15 cm (`stop_cm`) in front | **refuses** any forward move, including arcs |
| Something comes within 15 cm **during** a forward move | **stops at once** |
| Something close in front, but he spins or reverses | allowed, so he can get away |
| Nothing close | normal driving |

Claude is told the distance in every status report and after each move or look, for example
`Distance sensor: ahead 42 cm` or `OBSTACLE 12 cm (the wheels refuse to go forward)`. When the reflex stops
him, his drive result says `STOPPED by your distance sensor: obstacle 12 cm ahead - refused to drive forward`.

**It backs up the camera, it doesn't replace it.** It sees a narrow cone straight ahead, so it can miss
thin chair legs, soft fabric (which absorbs the sound) and things at an angle. It also can't see drops such
as stairs or table edges.

## Wiring

**The sensor's ECHO pin outputs 5 V, which can damage a Pi pin. Never connect it directly.**

| Sensor pin | Connect to |
|---|---|
| VCC | Pi 5 V (pin 2 or 4) |
| GND | ground, shared with the Pi |
| TRIG | GPIO23 (pin 16) |
| ECHO | a **1 kΩ** resistor to GPIO24 (pin 18), and a **2 kΩ** resistor from GPIO24 to ground |

```
   sensor ECHO ──[ 1 kΩ ]──┬──── GPIO24 (pin 18)
                           │
                        [ 2 kΩ ]
                           │
                          GND
```

**Resistor options:** two 1 kΩ in a row make 2 kΩ. Other pairs with about a 1:2 ratio work too, such as
4.7 kΩ and 10 kΩ (gives about 3.4 V, still safe). **Or skip the resistors** with a 3.3 V sensor (the
HC-SR04P or RCWL-1601), whose ECHO connects straight to GPIO24.

**Where to buy:** a resistor assortment kit (search "resistor assortment 1/4 watt"), around $8-15, or a
local electronics shop. Starter kits often include some.

**Mounting:** at the front, facing straight ahead, at least a few centimetres above the floor, so it
doesn't see the floor itself.

## Switching it on

1. Wire it up with the Pi off.
2. In `config.toml` under `[sensor]`: `enabled = true`. Copy it over, restart Bob.
3. The log says `Distance sensor ready (trigger GPIO23, echo GPIO24, stops at 15 cm)`.
4. **Test it:** type `/range`, then hold your hand 10 cm in front of the sensor and `/range` again. The
   reading must change. A disconnected sensor reads as "clear", so this check matters.
5. With the wheels off the ground and your hand close: `/fwd 1` should be refused.

## Commands

| Command | Effect |
|---|---|
| `/range` (or `/sensor`) | the current reading and the stop distance |
| `/range stop 25` | change the stop distance (3-100 cm) until Bob restarts |
| `/range off` | **switches the reflex off** (for testing). The wheels will NOT stop for obstacles |
| `/range on` | switches it back on |

The status bar shows `dist 42cm` while the sensor is on.

## Settings

Under `[sensor]`:

| Setting | Default | What it does |
|---|---|---|
| `enabled` | false | switch the sensor on |
| `trigger_pin` | 23 | the GPIO for TRIG |
| `echo_pin` | 24 | the GPIO for ECHO (through the resistor divider) |
| `stop_cm` | 15 | forward moves are refused or stopped inside this distance |
| `max_cm` | 200 | the furthest it measures; beyond this counts as "clear" |

## Troubleshooting

| Problem | Fix |
|---|---|
| Always reads "clear", even with your hand in front | check the wiring, especially ECHO through the divider and the shared ground |
| `Distance sensor unavailable` in the log | the pins are in use or wrong, or GPIO isn't available |
| Readings jump around | normal on soft or angled surfaces; mount it facing straight ahead |
| He stops too early or too late | adjust `stop_cm` |
| He won't drive forward at all | something is within `stop_cm`, or the sensor sees the floor: angle it up slightly |
