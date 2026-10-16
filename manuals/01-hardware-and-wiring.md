# Manual 01: Hardware and wiring

This manual covers Bob's physical parts: what connects where, how to power everything safely, and how
to check your wiring. Pin numbers in this manual come in two kinds, so watch which one you're reading:

- **GPIO number** (also called BCM number), such as GPIO12. This is what `config.toml` uses.
- **Physical pin**, such as pin 32. This is the pin's position on the Pi's 40-pin header, counting from
  pin 1 at the corner nearest the SD card (odd pins on the inside row, even pins on the outside row).

---

## Parts list

| Part | What Bob uses it for | Notes |
|---|---|---|
| Raspberry Pi 4B | Bob's computer | needs its own 5 V 3 A USB-C power supply |
| TB6612FNG motor driver board | runs the two wheel motors | handles about 1.2 A per motor |
| 2 × DC gear motors (yellow "TT" type) | the wheels | 3-6 V motors |
| Motor battery (4 × AA, about 6 V) | power for the motors only | never powers the Pi |
| USB camera, or a Pi camera module | Bob's eyes | see [manual 07](07-camera-stream-and-dashboard.md) |
| USB microphone | Bob's ears (optional) | see [manual 11](11-microphone-and-wake-word.md) |
| Speaker | Bob's voice | plugged into the Pi's 3.5 mm jack, or USB |
| HC-SR04 ultrasonic sensor | obstacle reflex (optional) | needs two resistors, see below |
| Push button | physical emergency stop (optional) | any momentary button |
| Jumper wires, a breadboard | connections | |

Bob can also drive with **continuous-rotation servos** instead of DC motors. That option is covered at
the end of this manual.

---

## The golden rules of wiring

1. **Separate power, shared ground.** The motors get their own battery. The Pi gets its own USB-C supply.
   The two never share a positive (+) wire, but their grounds (−) **must** be connected together. Without
   a shared ground the Pi's signals mean nothing to the motor board.
2. **Never power motors or servos from the Pi's 5 V pins.** A motor starting up or stalling draws enough
   current to make the Pi reboot, and can damage it.
3. **Wire with everything switched off.** Batteries out, Pi unplugged. Check, then power the Pi first and
   connect the motor battery last.
4. **Red to +, black to −.** Reversing a power connection can destroy a board instantly. Motor wires are
   the only ones where swapping doesn't matter (it just reverses the wheel).

---

## Pin map: everything Bob uses

| Physical pin | GPIO | Used for | Notes |
|---|---|---|---|
| 1 | 3.3 V | TB6612FNG **VCC** (logic power) | |
| 2 or 4 | 5 V | HC-SR04 **VCC** | low current only; never motors |
| 16 | GPIO23 | HC-SR04 **TRIG** | optional sensor |
| 18 | GPIO24 | HC-SR04 **ECHO**, through a voltage divider | **never connect directly** |
| 29 | GPIO5 | TB6612FNG **AIN1** | left motor direction |
| 31 | GPIO6 | TB6612FNG **AIN2** | left motor direction |
| 32 | GPIO12 | TB6612FNG **PWMA** | left motor speed (hardware PWM) |
| 33 | GPIO13 | TB6612FNG **PWMB** | right motor speed (hardware PWM) |
| 34 | GND | common ground | any GND pin works: 6, 9, 14, 20, 25, 30, 34, 39 |
| 36 | GPIO16 | TB6612FNG **BIN1** | right motor direction |
| 37 | GPIO26 | optional E-stop button | suggested; set `estop_button_pin = 26` |
| 38 | GPIO20 | TB6612FNG **BIN2** | right motor direction |
| 40 | GPIO21 | TB6612FNG **STBY** | standby: low = both motors off |

Every motor pin can be changed in `config.toml` under `[drive]` if you wire differently. See the
[settings reference](15-settings-reference.md).

---

## The motor driver (TB6612FNG)

The TB6612FNG takes small signals from the Pi and switches the battery's power to the motors.

| TB6612FNG pin | Connect to |
|---|---|
| **VM** | motor battery **+** (4.5-13.5 V; a 4×AA pack gives about 6 V) |
| **VCC** | Pi **3.3 V** (physical pin 1) |
| **GND** | motor battery **−** *and* a Pi ground (for example physical pin 34) |
| **STBY** | GPIO21 (pin 40) |
| **PWMA**, **AIN1**, **AIN2** | GPIO12, GPIO5, GPIO6 (pins 32, 29, 31) |
| **PWMB**, **BIN1**, **BIN2** | GPIO13, GPIO16, GPIO20 (pins 33, 36, 38) |
| **AO1 / AO2** | the left motor's two wires (either way round) |
| **BO1 / BO2** | the right motor's two wires (either way round) |

Breakout boards usually have several GND pins. They are all connected inside the board, so use any one.

**What the pins do:**
- **PWMA / PWMB** set each motor's speed by switching power on and off very fast (20,000 times a second).
- **AIN1/AIN2** and **BIN1/BIN2** set each motor's direction.
- **STBY** switches the whole board on and off. Bob holds it high while running and pulls it low on an
  emergency stop or shutdown, which cuts power to both motors.

### Steady PWM: the one-time Pi setting

GPIO12 and GPIO13 are the Pi's two hardware PWM pins. They produce perfectly steady speed signals once
this line is in `/boot/firmware/config.txt` (`install.sh` adds it):

```
dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4
```

Reboot after adding it. `ls /sys/class/pwm/` should then show `pwmchip0`. Without it, Bob falls back to
software PWM, which works fine for DC motors but makes servos jitter. The overlay doesn't interfere with
the 3.5 mm audio jack (tested on your Pi).

---

## The motors (yellow TT gear motors)

These are typical figures. Check the listing for your exact motors.

| | Typical TT motor (1:48 gearbox) |
|---|---|
| Voltage | 3-6 V rated. **Don't feed it 9 V or more** |
| Speed | about 200 rpm at 6 V with no load. With a 65 mm wheel that's about 0.7 m/s, which is fast for Bob, so his speed cap matters |
| Current | about 150-250 mA running, **0.5-1 A or more when stalled** |

**Tips:**
- **Battery:** 4×AA (6 V, or 4.8 V with rechargeables) is a good match. 2×AA (3 V) is too weak to turn
  the wheels under load. A 5 V USB power bank works too, but the motors are slower and weaker.
- **Noise capacitor:** solder a 100 nF ceramic capacitor across each motor's two tabs. It reduces the
  electrical noise from the motor's brushes that can upset the Pi and the camera. It has no polarity.
- **Direction:** the motors face opposite ways on each side, so one has to spin backwards to drive
  forward. Bob handles that with `right_invert = true`. If a wheel goes the wrong way on `/fwd 1`, flip
  that wheel's `left_invert` or `right_invert` setting rather than rewiring.
- **Over 6 V?** Lower `max_speed` so the motors aren't overdriven (about 0.6 at 9 V).

**Body and balance:**
- Mount the battery as low as possible and the motors wide apart.
- Add a small skid or caster at the back. If a wheel jams, the motor pushes back on the body, and a
  low, wide robot with a skid won't tip.

---

## Camera, microphone and speaker

| Part | How it connects | Setting |
|---|---|---|
| USB camera | any USB port | `[camera] source = "usb"` or `"auto"` |
| Pi camera module | the CSI ribbon connector | `[camera] source = "csi"` or `"auto"` |
| USB microphone | any USB port | `[mic] device = "plughw:CARD=Device,DEV=0"` (your current setting) |
| Speaker | the 3.5 mm jack or USB | `[audio] device` (empty = the Pi's default) |

Mount the camera facing forward, level, as high as practical. If its picture is upside down, set
`rotate_180 = true`. Keep the microphone away from the motors and the speaker.

---

## Distance sensor (HC-SR04), optional

**The ECHO pin outputs 5 V, which can damage a Pi pin. Always divide it down:**

| Sensor pin | Connect to |
|---|---|
| VCC | 5 V (Pi pin 2 or 4 is fine for this small sensor) |
| GND | ground (shared with the Pi) |
| TRIG | GPIO23 (pin 16) |
| ECHO | a **1 kΩ** resistor to GPIO24 (pin 18), and a **2 kΩ** resistor from GPIO24 to ground |

```
   sensor ECHO ──[ 1 kΩ ]──┬──── GPIO24 (pin 18)
                           │
                        [ 2 kΩ ]
                           │
                          GND
```

No 2 kΩ resistor? Two 1 kΩ in a row make 2 kΩ, or use 4.7 kΩ + 10 kΩ (about 3.4 V, still safe). Or
buy a 3.3 V version of the sensor (HC-SR04P or RCWL-1601), whose ECHO can connect directly. Full
details: [manual 09](09-distance-sensor.md).

## Physical emergency-stop button, optional

Wire a push button between a free GPIO (GPIO26, pin 37, is suggested) and any ground pin. Then set
`estop_button_pin = 26` under `[drive]`. Pressing it does exactly what Space does in the console: cuts
the motors and pauses Bob. Avoid GPIO 5, 6, 12, 13, 16, 20, 21, 23 and 24, which are already in use.

---

## Alternative: servos instead of DC motors

Bob still supports continuous-rotation servos (for example FS90R). Set `type = "servo"` under `[drive]`.

| Part | Connect to |
|---|---|
| Left servo signal (orange) | GPIO12 (pin 32) |
| Right servo signal (orange) | GPIO13 (pin 33) |
| Servo power (red) | a separate 5 V supply (4×AA or a regulator), **not** the Pi |
| Servo ground (brown) | that supply's ground, **and** a Pi ground |

**Standard 180° servos, like the common SG90, won't work as wheels.** They turn to an angle and hold it,
so they just twitch. Bob needs "continuous rotation" or "360°" servos.

---

## Wiring checklist (do this before the first power-on)

- [ ] Motor battery **+** goes only to TB6612FNG **VM**.
- [ ] Motor battery **−**, TB6612FNG **GND** and a Pi **GND** are all connected together.
- [ ] TB6612FNG **VCC** is on the Pi's **3.3 V** (pin 1), not 5 V.
- [ ] Nothing from the motor battery touches a Pi 5 V or 3.3 V pin.
- [ ] The HC-SR04 ECHO goes through the resistor divider (if fitted).
- [ ] Each motor's two wires are on its own pair (AO1/AO2 or BO1/BO2).
- [ ] Wheels are off the ground for the first test.
- [ ] Power the Pi first, start Bob with `--paused`, then connect the motor battery.

## Troubleshooting

| Problem | Likely cause | Fix |
|---|---|---|
| Nothing moves, log says `TB6612FNG ready` | no shared ground, or STBY not wired | check the ground link and GPIO21 |
| Nothing moves, log says `DRIVE UNAVAILABLE` | a pin is in use or GPIO isn't available | read the reason in the log; check no other program uses the pins |
| One wheel spins backwards | normal for mirrored motors | flip `left_invert` / `right_invert` |
| A wheel hums but doesn't turn at low speed | not enough power at low duty | raise `/minduty` (try 0.35) |
| The Pi reboots when the motors start | motors powered from the Pi | give the motors their own battery |
| Bob drifts left or right | the two motors differ | `/trim` or `/calibrate straight` ([manual 06](06-calibration.md)) |
| Servos twitch instead of spinning | standard (not continuous) servos | use continuous-rotation servos |

More problems and fixes: [Troubleshooting](17-troubleshooting.md).
