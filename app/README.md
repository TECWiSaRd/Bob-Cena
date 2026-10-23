# Bob app

Flutter app for Mac and Android: live camera, driving, chat, status, and Bob's secure pairing. See `manuals/25-the-bob-app.md`.

```bash
flutter pub get
flutter analyze
flutter test                                      # BOB_PYTHON=python3 so the tests can start the real Python server
flutter run -d macos
```

`lib/src/` — `client.dart` (pinned HTTPS client), `pairing.dart` (the proofs; they must match `appapi.py`), `mjpeg.dart`, `discovery.dart`
(Bonjour), `app_state.dart`, and the screens. `test/against_python_test.dart` runs `tests/app_test_server.py`, the real server code.
