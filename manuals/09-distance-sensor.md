# Manual 09: Distance sensor (HC-SR04)

An ultrasonic distance sensor gives Bob a reflex: the wheels refuse to drive into anything close in front of
him, **whatever Claude decided**. It works like a bat: it sends out a click too high to hear and times the
echo.

> **Status:** optional. The ultrasonic sensor and the laser sensor are both **tested only with simulated
> sensors so far**; neither has been confirmed on a real Bob. Bob works normally without them.

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

## The laser sensor (VL53L1X), optional

A small laser distance sensor on the Pi's I2C pins. It reads soft things (sofas, clothes, pets) and angled
walls that ultrasonic misses, and it needs **no resistors**. It can miss glass and mirrors, and bright sunlight
confuses it, which is why using it **together** with the ultrasonic sensor is a good idea: each one covers the
other's weak spot, and **the nearer reading always wins**. Range is about 4 cm to 4 m.

| Sensor pin | Connect to |
|---|---|
| VIN | Pi 3.3 V (pin 1) |
| GND | ground (pin 6) |
| SDA | GPIO2 (pin 3) |
| SCL | GPIO3 (pin 5) |

1. Switch I2C on once: `sudo raspi-config`, Interface Options, I2C, Yes, then reboot.
2. Install its library: `.venv/bin/pip install vl53l1x` (from Bob's folder on the Pi).
3. Check the Pi sees it: `sudo apt install -y i2c-tools && i2cdetect -y 1`. A `29` should appear in the table.
4. In `config.local.toml`:
   ```toml
   [sensor]
   enabled = true
   tof = true
   ultrasonic = true      # false if you only have the laser
   ```
5. Restart Bob. The log says `Laser sensor ready (I2C bus 1, address 0x29)`. If something is wrong it says
   `Laser sensor unavailable (...)` and the ultrasonic sensor keeps working on its own.

`/range` then shows the nearer reading with both in brackets, like `ahead 42 cm [ultrasonic 42, laser 45]`.
If a sensor gives no reading for a moment, the other one is used. If a laser reading is older than about half a
second it is ignored, so a stuck sensor can't leave an old number in charge.

**Test it the same way:** hold your hand 10 cm in front and `/range`. The reading must change.

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
| `enabled` | false | switch the obstacle reflex on (needs at least one sensor below) |
| `ultrasonic` | true | use the HC-SR04 |
| `tof` | false | use a VL53L1X laser sensor (see above) |
| `tof_bus` | 1 | the Pi's I2C bus number |
| `tof_address` | 0x29 | the laser sensor's address |
| `trigger_pin` | 23 | the GPIO for TRIG |
| `echo_pin` | 24 | the GPIO for ECHO (through the resistor divider) |
| `stop_cm` | 15 | forward moves are refused or stopped inside this distance |
| `max_cm` | 200 | the furthest it measures; beyond this counts as "clear" |

## Troubleshooting

| Problem | Fix |
|---|---|
| Always reads "clear", even with your hand in front | check the wiring, especially ECHO through the divider and the shared ground |
| `Laser sensor unavailable` in the log | I2C isn't switched on, `vl53l1x` isn't installed, or a wire is loose (`i2cdetect -y 1` should show `29`) |
| `no reading right now` | the sensor is working but has nothing in range or its last reading was rejected; the other sensor, if any, is still used |
| `Ultrasonic sensor unavailable` in the log | the pins are in use or wrong, or GPIO isn't available |
| Readings jump around | normal on soft or angled surfaces; mount it facing straight ahead |
| He stops too early or too late | adjust `stop_cm` |
| He won't drive forward at all | something is within `stop_cm`, or the sensor sees the floor: angle it up slightly |
