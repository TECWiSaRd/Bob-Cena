# Bob bridge: the micro:bit that stays plugged into the Pi by USB (V1 or V2). It passes the handheld's radio messages to the Pi
# and Bob's "MODE ..." answers back. Set GROUP to the same number as the handheld (bob_remote.py).
from microbit import *
import radio

GROUP = 42

radio.config(group=GROUP, power=6)
radio.on()
uart.init(baudrate=115200)
display.show(Image.DIAMOND_SMALL)

while True:
    msg = radio.receive()
    while msg:
        if len(msg) <= 60:
            uart.write(msg + "\n")
        msg = radio.receive()
    if uart.any():
        data = uart.readline()
        if data:
            try:
                text = str(data, "ascii").strip()
            except Exception:
                text = ""
            if text.startswith("MODE "):
                radio.send(text)
    sleep(20)
