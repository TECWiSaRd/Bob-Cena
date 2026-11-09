# Bob remote: the handheld micro:bit (works on V1 and V2). Paste into https://python.microbit.org and flash it.
#
#   hold A and tilt     drive (let go of A and Bob stops)
#   tap B               manual driving on / off
#   A and B together    EMERGENCY STOP
#   logo touch (V2)     push-to-talk
#   hold B for 3 s      release the emergency stop (only if Bob's config says allow_clear = true)
#
# Plugged into the Pi by USB it talks over the cable. Otherwise it uses the radio to a second micro:bit
# (bob_bridge.py) that is plugged into the Pi. Set GROUP to the same number on both. The radio is NOT secure:
# set KEY here and in Bob's config.local.toml ([microbit] key = "...") so strangers' micro:bits are ignored.
from microbit import *
import radio

GROUP = 42       # 0..255, the same on the bridge
KEY = ""         # a short word with no spaces, the same as [microbit] key in Bob's config; "" = none

radio.config(group=GROUP, power=6)
radio.on()
uart.init(baudrate=115200)

ICONS = {"idle": Image.HAPPY, "drive": Image.ARROW_N, "estop": Image.NO}
b_down_since = None
cleared = False
was_a = False


def send(text):
    line = text + (" " + KEY if KEY else "") + "\n"
    radio.send(line.strip())          # to the bridge, if there is one
    uart.write(line)                  # to the Pi, if plugged in


def get_mode():
    m = None
    if uart.any():
        data = uart.readline()
        if data:
            try:
                m = str(data, "ascii").strip()
            except Exception:
                m = None
    if m is None:
        m = radio.receive()
    if m and m.startswith("MODE "):
        return m[5:]
    return None


while True:
    a, b = button_a.is_pressed(), button_b.is_pressed()
    if a and b:
        uart.write("E\n")             # the emergency stop never needs the key
        radio.send("E")
        display.show(Image.NO)
        sleep(500)
        continue
    if a:
        x = max(-100, min(100, accelerometer.get_x() // 8))      # +-800 milli-g is full tilt
        y = max(-100, min(100, -accelerometer.get_y() // 8))     # tilt away from you = forward
        send("D %d %d" % (x, y))
    elif was_a:
        send("D 0 0")                 # A let go: stop at once
    was_a = a
    # B: a tap switches manual driving, a long hold asks to release the e-stop
    if b and not a:
        if b_down_since is None:
            b_down_since = running_time()
            cleared = False
        elif not cleared and running_time() - b_down_since > 3000:
            send("C")
            cleared = True
    else:
        if b_down_since is not None and not cleared and running_time() - b_down_since < 800 and not a:
            send("M")
        b_down_since = None
    try:
        if pin_logo.is_touched():
            send("T")
            sleep(400)
    except Exception:
        pass                          # V1 has no touch logo
    mode = get_mode()
    if mode in ICONS:
        display.show(ICONS[mode])
    sleep(100)
