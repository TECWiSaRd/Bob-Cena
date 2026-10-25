# Manual 25: The Bob app (Mac and Android)

A proper app for driving Bob, watching his camera, chatting with him and checking on him, with a secure connection that is **on
by default** and nothing to configure. It lives in the `app/` folder (Flutter), and talks to a secure port Bob opens (HTTPS, 8443).

**Status:** the connection code is tested **against the real Python server**: pairing, the certificate pinning, commands, driving,
video, unpairing and the failure cases. The Mac app builds and starts, and its screens are covered by widget tests. **I haven't been
able to use the app by eye on a real Bob, and the Android version has not been built or run** (this computer has no Android build
tools); the Android code is the same as the Mac code. Expect to adjust the look and the feel.

---

## What you get

The app opens on a **home page**: the BOB name, whether he's online, "Welcome back, *your name*." and three cards: what he's doing right now, what
Claude has cost today (and all time), and the Pi's temperature (or which room he's in). Tap a card for the details. **Scroll down** (or swipe up) and the welcome page really scrolls away upwards while a second, white screen rises from below with
three rounded cards on it, and the four icons glide out from the bottom bar to the edges of the screen. The cards show what he's thinking, **who's on** (people on the shared console, app devices used in the last two minutes, web dashboard users) and
his recent tasks. Scroll back up and everything returns. Let go half way and it finishes the move by itself. The bar along the bottom has four icons;
tap one to open that section, and tap it again (or tap the BOB name) to go back home. It follows your device's light or dark setting by default; under **More, Appearance** you can force **Light** or **Dark**, or go back to **Auto** (follow the device). The choice is remembered.

The welcome uses the name you give when you pair (or "Adam" from a device called "Adam's Mac"); change it under More. The fonts are bundled
(open licences, `app/assets/fonts`). The look is based on `temp/bobapp-homereference.png`.

| Section | |
|---|---|
| **Drive** | live camera, a thumb stick (or W A S D / arrows and Space = emergency stop on a Mac), a Slow switch, and two on/off switches: **AI thinking** and **Follow me** |
| **Status** | what he's doing, what Claude has cost (this run, today, all time), the Pi's temperature, load, memory and power warnings, recent events |
| **Chat** | the live log, and a box to talk to him or type a `/command` |
| **More** | on/off switches for **AI thinking, Follow me, Sleep, Sound, Camera and Emergency stop** (blue or red when on, white when off; the screen changes at once and flips back if Bob can't be reached), `/check`, `/usage`, **go to a room** (the Go button becomes Stop while he's on the way), light/dark, music, and unpairing |

The red **EMERGENCY STOP** button is on every screen, home included. (It isn't in the reference design, but a robot that moves needs a stop button within reach.) A banner appears if he can't be reached or if the e-stop is on.

## First time: pairing (about a minute)

1. Make sure Bob is running with `[stream] https = true` (the default) and `openssl` is installed (`sudo apt-get install -y openssl avahi-utils`).
   The first start makes his certificate.
2. In Bob's console (or `bob-console`), type **`/pair`**. It shows a code like `K7PQ-2M9X-4TWD`, good for 5 minutes and one device.
3. Open the app. **Add Bob** lists the Bobs it finds on the network (Bonjour). Pick yours, or type `bobcena.local:8443`.
4. Enter the code and a name for this device ("Adam's Mac"), and tap **Pair**.

That's it: from then on the app opens straight to Bob. `/devices` in Bob's console lists every paired device and `/devices remove NAME`
removes one (it must pair again).

## How the connection stays secure

- **Encrypted.** Everything goes over HTTPS. Bob makes his own certificate the first time (in `certs/`, never committed).
- **Pinned.** When you pair, the app remembers the exact certificate and from then on refuses any other, so a stranger on the Wi-Fi who
  pretends to be Bob is rejected. (A normal browser would show a warning for a self-made certificate; the app doesn't need to trust anyone but Bob.)
- **The code is never sent.** App and Bob each *prove* they know it (a keyed hash that also covers the certificate), and the code is 12
  characters, one use, five minutes. Someone in the middle can neither learn it nor reuse it. Wrong guesses lock an address out for a minute.
- **A token per device.** Pairing gives that device its own secret token. Bob keeps only a hash of it (`devices.json`). Unpairing a device
  cuts it off at once, even a video stream already running.
- **Same limits as the web dashboard.** A paired device can do what the phone dashboard can (drive, pause, chat, sleep, go to a room...). It
  cannot `/quit`, wipe notes, run `/update`, pair other devices, or power the Pi off (unless you allow `"dashboard"` under `[power]`, manual 21).
- **Only the app API is on the secure port.** The browser pages are not served there, so adding HTTPS doesn't open the dashboard to your network.

**Things to know.** The token is kept in the app's private storage on the device, not in the system keychain. Bob announces himself on the
network (name and a short piece of his certificate's fingerprint), which anyone on the same network can see; pairing still needs your code.
Deleting Bob's `certs/` folder makes a new certificate and every device has to pair again.

## Finding Bob again when his address changes

The app remembers where Bob was. If it can't reach him for a few seconds it looks for him with Bonjour and, if it finds a Bob with the
same certificate, follows him to his new address. This works on the same network. Across houses (a friend's Wi-Fi) he gets a new address and
the app finds him again the same way; the pairing stays valid.

## Building the app (on your Mac)

```bash
cd app
flutter pub get
flutter test                              # unit and widget tests (the Python server tests need BOB_PYTHON=python3)
flutter run -d macos                      # run it
flutter build macos                       # a Bob.app in build/macos/Build/Products/Release/
```
**Android:** install Android Studio (it adds the command-line tools), run `flutter doctor --android-licenses`, plug in a phone with USB
debugging on, then `flutter run -d <phone>` or `flutter build apk`. Allow "nearby devices / local network" if asked. The Bonjour search needs
the phone on the same Wi-Fi as Bob.

## Sharing it with friends

**The easy way: let GitHub build it.** `.github/workflows/build-app.yml` builds the Mac app and the Android APK on GitHub's own computers
(no Android tools needed on your Mac) after running the tests. Either:
- **publish a release** on GitHub (Releases, Draft a new release, choose a tag, Publish): the workflow attaches `Bob-mac.zip` and
  `Bob-android.apk` to it a few minutes later; or
- open the repository's **Actions** tab, choose **Build the Bob app**, **Run workflow**, then download the files from that run's page.

Friends you add to the private repository (Settings, Collaborators) can download from the release page; or download the files yourself and send them.

**Opening it, the first time**
- *Mac:* unzip it and try to open **Bob.app**; macOS blocks it because it isn't signed with an Apple developer identity (it isn't malware). Click
  Done, then **System Settings, Privacy & Security, scroll to Security, "Bob was blocked", Open Anyway**, and confirm. Once per Mac. (On macOS 14 and
  older, right-click, Open also works; on 15 and later it doesn't.) If it says the app is "damaged", run `xattr -cr` on it once, then repeat the steps above.
  Signing and notarising it properly needs an Apple Developer account ($99 a year); not set up.
- *Android:* open the APK; allow "install unknown apps" for the browser or file app when asked. The APK is signed with a debug key, which is fine for sideloading.

**Each friend pairs their own device** with a code from `/pair` (manual 25, above), on the same network as Bob.

**Building the Mac app yourself.** `flutter build macos --release` makes a universal (Apple and Intel) app. On a very new macOS beta it can stop with
"does not contain architectures arm64 x86_64"; build for this Mac's chip only instead:
`FLUTTER_XCODE_ARCHS=arm64 flutter build macos --release`, then
`ditto -c -k --keepParent build/macos/Build/Products/Release/Bob.app Bob-mac.zip`. (That zip works on Apple-silicon Macs only; GitHub's build makes the universal one.)
I tried this here: the zip is 8.7 MB and the unzipped app starts.

## Troubleshooting

| Problem | Fix |
|---|---|
| `/pair` says the secure port isn't running | check the log for `HTTPS (the Bob app) is off:`; install openssl, or look for a port clash on 8443 |
| The app doesn't list Bob | not on the same network, or `avahi-utils` isn't installed on the Pi (`sudo apt-get install -y avahi-utils`, restart Bob). Type `bobcena.local:8443` or his IP instead |
| "that code didn't work" | it expired (5 minutes), was used, or has a typo; run `/pair` again |
| "his answer did not check out" | the reply wasn't from the Bob that made the code. Nothing was saved. Pair again on a network you trust |
| "The certificate doesn't match" | something else is answering at Bob's address, or his `certs/` folder was recreated. If it was you, unpair and pair again |
| "Bob no longer recognises this device" | it was removed with `/devices remove`; tap Pair again |
| No picture | the camera is off (`/camera on`), or the camera is stuck (`/check`) |
| Mac asks to allow local network access | allow it; without it Bonjour can't find Bob (you can still type his address) |
