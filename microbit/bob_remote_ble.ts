// Bob remote over Bluetooth (micro:bit V2). Open https://makecode.microbit.org, make a new project, click the
// {} JavaScript tab at the top, and paste all of this. Then:
//   1. gear icon > Extensions > add "bluetooth"   (if it asks to remove the radio extension, say yes)
//   2. gear icon > Project Settings > Bluetooth: choose "Just Works Pairing" (or "Passkey" for more security)
//   3. download to the micro:bit. To pair it with the Pi, see manual 27.
//
//   hold A and tilt     drive (let go of A and Bob stops)
//   tap B               manual driving on / off
//   A and B together    EMERGENCY STOP
//   logo touch          push-to-talk
//   hold B for 3 s      release the emergency stop (only if Bob's config says allow_clear = true)
//
// KEY must match [microbit] key in Bob's config.local.toml ("" = none).
let KEY = ""
let aWasDown = false
let bDownSince = -1
let cleared = false

function send(text: string) {
    bluetooth.uartWriteLine(KEY == "" ? text : text + " " + KEY)
}

bluetooth.startUartService()
bluetooth.onBluetoothConnected(function () {
    basic.showIcon(IconNames.Happy)
})
bluetooth.onBluetoothDisconnected(function () {
    basic.showIcon(IconNames.SmallDiamond)
})
bluetooth.onUartDataReceived(serial.delimiters(Delimiters.NewLine), function () {
    let line = bluetooth.uartReadUntil(serial.delimiters(Delimiters.NewLine))
    if (line == "MODE idle") {
        basic.showIcon(IconNames.Happy)
    } else if (line == "MODE drive") {
        basic.showIcon(IconNames.ArrowNorth)
    } else if (line == "MODE estop") {
        basic.showIcon(IconNames.No)
    }
})
basic.showIcon(IconNames.SmallDiamond)

basic.forever(function () {
    let a = input.buttonIsPressed(Button.A)
    let b = input.buttonIsPressed(Button.B)
    if (a && b) {
        bluetooth.uartWriteLine("E")          // the emergency stop never needs the key
        basic.showIcon(IconNames.No)
        basic.pause(500)
        return
    }
    if (a) {
        // +-800 milli-g is full tilt; tilt away from you = forward
        let x = Math.constrain(Math.idiv(input.acceleration(Dimension.X), 8), -100, 100)
        let y = Math.constrain(Math.idiv(0 - input.acceleration(Dimension.Y), 8), -100, 100)
        send("D " + x + " " + y)
    } else if (aWasDown) {
        send("D 0 0")                          // A let go: stop at once
    }
    aWasDown = a
    // B: a tap switches manual driving, a long hold asks to release the e-stop
    if (b && !a) {
        if (bDownSince < 0) {
            bDownSince = input.runningTime()
            cleared = false
        } else if (!cleared && input.runningTime() - bDownSince > 3000) {
            send("C")
            cleared = true
        }
    } else {
        if (bDownSince >= 0 && !cleared && input.runningTime() - bDownSince < 800 && !a) {
            send("M")
        }
        bDownSince = -1
    }
    if (input.logoIsPressed()) {               // delete these three lines on a V1 (it has no touch logo, and no Bluetooth room)
        send("T")
        basic.pause(400)
    }
    basic.pause(100)
})
