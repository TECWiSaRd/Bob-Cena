// The Bluetooth card on the Drive tab, with a pretend radio.
import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:bob_app/src/app_state.dart';
import 'package:bob_app/src/ble_codec.dart';
import 'package:bob_app/src/ble_link.dart';
import 'package:bob_app/src/client.dart';
import 'package:bob_app/src/home_screen.dart';
import 'package:bob_app/src/profile.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

const _key = 'ab';

/// A pretend Bob on the radio: answers a hello with a nonce (or a refusal) and remembers every line the app sent.
class FakeRadio implements BleTransport {
  FakeRadio({this.helloAnswer = 'N 0011223344556677'});
  final String helloAnswer;
  final _in = StreamController<List<int>>.broadcast();
  final _conn = StreamController<bool>.broadcast();
  final lines = <String>[];
  final _assembler = BleLineAssembler();
  bool connected = false;
  bool failToConnect = false;

  @override
  Stream<List<int>> get incoming => _in.stream;
  @override
  Stream<bool> get connection => _conn.stream;

  @override
  Future<void> connect() async {
    if (failToConnect) throw BleException("Couldn't find Bob over Bluetooth.");
    connected = true;
  }

  @override
  Future<void> write(Uint8List packet) async {
    for (final line in _assembler.feed(packet)) {
      lines.add(line);
      if (line.startsWith('H ')) {
        scheduleMicrotask(() => _in.add(utf8.encode('$helloAnswer\n')));
      }
    }
  }

  @override
  Future<void> disconnect() async => connected = false;

  void drop() => _conn.add(false);
}

class FakeBob extends BobClient {
  FakeBob() : super(host: 'x', port: 1);
  bool asked = false;
  Map<String, dynamic> answer = {
    'key': 'cd' * 32,
    'device': 'a1b2c3d4',
    'enabled': true,
  };

  @override
  Future<Map<String, dynamic>> bleKey() async {
    asked = true;
    return answer;
  }

  @override
  Future<Map<String, dynamic>> status() async => {
    'mode': 'AUTO',
    'rooms': [],
    'log': [],
    'usage': {},
    'vitals': {},
  };

  @override
  Stream<Uint8List> video() => StreamController<Uint8List>().stream;
}

AppState stateWith(
  FakeRadio radio, {
  bool key = true,
  bool online = true,
  FakeBob? bob,
}) {
  final s = AppState(autoConnect: false, bleTransport: () => radio);
  s.loading = false;
  s.profile = BobProfile(
    name: 'Bob',
    host: 'x',
    port: 1,
    fingerprint: 'ab' * 32,
    token: 't',
    device: 'My Mac',
    bleKey: key ? _key * 32 : null,
    bleDevice: key ? 'a1b2c3d4' : null,
  );
  s.profiles = [s.profile!];
  s.client = bob ?? FakeBob();
  s.online = online;
  return s;
}

Future<void> openDrive(WidgetTester tester, AppState s) async {
  tester.view.physicalSize = const Size(1366, 1200);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    ChangeNotifierProvider<AppState>.value(
      value: s,
      child: const MaterialApp(home: HomeScreen()),
    ),
  );
  await tester.pump();
  await tester.tap(find.byKey(const Key('nav-drive')));
  await tester.pumpAndSettle();
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('with a key, Connect connects and then the card says so', (
    tester,
  ) async {
    final radio = FakeRadio();
    final s = stateWith(radio);
    await openDrive(tester, s);
    expect(find.byKey(const Key('ble-connect')), findsOneWidget);
    expect(find.textContaining('no Wi-Fi'), findsOneWidget);

    await tester.runAsync(() async {
      await s.connectBluetooth();
    });
    await tester.pumpAndSettle();
    expect(s.usingBluetooth, isTrue);
    expect(find.text('Driving over Bluetooth'), findsOneWidget);
    expect(find.byKey(const Key('ble-disconnect')), findsOneWidget);
    expect(find.byKey(const Key('ble-connect')), findsNothing);
    expect(radio.lines.first, startsWith('H a1b2c3d4'));
    await tester.runAsync(s.disconnectBluetooth);
    s.dispose();
  });

  testWidgets(
    'driving goes over Bluetooth once connected, and nothing is sent when it is not',
    (tester) async {
      final radio = FakeRadio();
      final s = stateWith(radio);
      await openDrive(tester, s);
      await tester.runAsync(() async {
        await s.drive(
          0.5,
          0.5,
        ); // not connected: this goes to Wi-Fi (the pretend Bob ignores it)
      });
      expect(radio.lines, isEmpty);
      await tester.runAsync(() async {
        await s.connectBluetooth();
        await s.drive(0.5, -0.5);
        await s.drive(0, 0);
      });
      final signed = radio.lines.where((l) => !l.startsWith('H ')).toList();
      expect(signed.first, startsWith('D a1b2c3d4 1 0.50 -0.50 '));
      expect(signed.last, startsWith('S a1b2c3d4 2 '));
      await tester.runAsync(s.disconnectBluetooth);
      s.dispose();
    },
  );

  testWidgets(
    'the emergency stop goes out over Bluetooth even when the link is signed in',
    (tester) async {
      final radio = FakeRadio();
      final s = stateWith(radio);
      await openDrive(tester, s);
      await tester.runAsync(() async {
        await s.connectBluetooth();
        await s.send('/estop');
        await Future<void>.delayed(const Duration(milliseconds: 100));
      });
      expect(radio.lines, contains('E'));
      expect(
        radio.lines.any((l) => l.startsWith('E a1b2c3d4 ')),
        isTrue,
      ); // and the signed form
      await tester.runAsync(s.disconnectBluetooth);
      s.dispose();
    },
  );

  testWidgets('a refusal from Bob is shown in plain words', (tester) async {
    final radio = FakeRadio(helloAnswer: 'ERR unknown device');
    final s = stateWith(radio);
    await openDrive(tester, s);
    await tester.runAsync(() async {
      await s.connectBluetooth();
    });
    await tester.pumpAndSettle();
    expect(s.usingBluetooth, isFalse);
    expect(find.byKey(const Key('ble-problem')), findsOneWidget);
    expect(find.textContaining("doesn't know this device"), findsOneWidget);
    s.dispose();
  });

  testWidgets('not finding Bob is shown, and the button comes back', (
    tester,
  ) async {
    final radio = FakeRadio()..failToConnect = true;
    final s = stateWith(radio);
    await openDrive(tester, s);
    await tester.runAsync(() async {
      await s.connectBluetooth();
    });
    await tester.pumpAndSettle();
    expect(find.textContaining("Couldn't find Bob"), findsOneWidget);
    expect(find.byKey(const Key('ble-connect')), findsOneWidget);
    s.dispose();
  });

  testWidgets('Disconnect goes back to the Connect button', (tester) async {
    final radio = FakeRadio();
    final s = stateWith(radio);
    await openDrive(tester, s);
    await tester.runAsync(() async {
      await s.connectBluetooth();
    });
    await tester.pumpAndSettle();
    await tester.runAsync(() async {
      await s.disconnectBluetooth();
    });
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('ble-connect')), findsOneWidget);
    expect(s.usingBluetooth, isFalse);
    s.dispose();
  });

  testWidgets('a link that drops is no longer used for driving', (
    tester,
  ) async {
    final radio = FakeRadio();
    final s = stateWith(radio);
    await openDrive(tester, s);
    await tester.runAsync(() async {
      await s.connectBluetooth();
      radio.drop();
      await Future<void>.delayed(const Duration(milliseconds: 50));
    });
    await tester.pumpAndSettle();
    expect(s.usingBluetooth, isFalse);
    expect(s.ble?.problem, contains('dropped'));
    await tester.runAsync(s.disconnectBluetooth);
    s.dispose();
  });

  testWidgets(
    'without a key the card offers to get one, only while there is Wi-Fi',
    (tester) async {
      final offline = stateWith(FakeRadio(), key: false, online: false);
      await openDrive(tester, offline);
      expect(find.textContaining('One-time setup'), findsOneWidget);
      expect(
        tester
            .widget<OutlinedButton>(find.byKey(const Key('ble-get-key')))
            .onPressed,
        isNull,
      );
      offline.dispose();
    },
  );

  testWidgets('Get key asks Bob and saves the key', (tester) async {
    final bob = FakeBob();
    final s = stateWith(FakeRadio(), key: false, bob: bob);
    await openDrive(tester, s);
    await tester.runAsync(() async {
      await s.prepareBluetooth();
    });
    await tester.pumpAndSettle();
    expect(bob.asked, isTrue);
    expect(s.bleAvailable, isTrue);
    expect(s.profile!.bleDevice, 'a1b2c3d4');
    expect(find.byKey(const Key('ble-connect')), findsOneWidget);
    s.dispose();
  });

  testWidgets(
    'if Bluetooth control is switched off on Bob, the key is kept and the card says what to change',
    (tester) async {
      final bob = FakeBob()
        ..answer = {'key': 'cd' * 32, 'device': 'a1b2c3d4', 'enabled': false};
      final s = stateWith(FakeRadio(), key: false, bob: bob);
      await openDrive(tester, s);
      await tester.runAsync(() async {
        await s.prepareBluetooth();
      });
      await tester.pumpAndSettle();
      expect(s.bleAvailable, isTrue);
      expect(find.textContaining('[ble] enabled = true'), findsOneWidget);
      s.dispose();
    },
  );

  test(
    'the key and short id are saved with the profile and come back',
    () async {
      final s = stateWith(FakeRadio());
      await s.setUserName('Adam'); // any save writes the profile list
      final again = AppState(autoConnect: false);
      await again.load();
      expect(again.profile!.bleKey, _key * 32);
      expect(again.profile!.bleDevice, 'a1b2c3d4');
      s.dispose();
      again.dispose();
    },
  );
}
