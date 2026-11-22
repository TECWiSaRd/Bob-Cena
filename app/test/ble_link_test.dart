// The app's Bluetooth code against Bob's REAL Bluetooth protocol code (blelink.BleCore in Python), on the same device list the real server
// uses. The radio is replaced by a pipe: each packet the app writes goes to the Python side, and what Bob would send back comes out. So this
// proves, end to end: pairing over HTTPS, getting the key, hello, signed drive / stop / status / commands, and that a wrong key moves nothing.
//
//   BOB_PYTHON=/path/to/python flutter test test/ble_link_test.dart
import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:bob_app/src/app_state.dart';
import 'package:bob_app/src/ble_codec.dart';
import 'package:bob_app/src/ble_link.dart';
import 'package:bob_app/src/client.dart';
import 'package:bob_app/src/profile.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'against_python_test.dart' show PyServer;

/// A radio made of a pipe to the Python side.
class PipeTransport implements BleTransport {
  PipeTransport(this.server);
  final PyServer server;
  final _in = StreamController<List<int>>.broadcast();
  final _conn = StreamController<bool>.broadcast();
  bool connected = false;
  final writes = <List<int>>[];

  @override
  Stream<List<int>> get incoming => _in.stream;
  @override
  Stream<bool> get connection => _conn.stream;

  @override
  Future<void> connect() async => connected = true;

  @override
  Future<void> write(Uint8List packet) async {
    if (!connected) throw BleException('not connected');
    writes.add(packet);
    final hex = packet.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
    final reply = await server.ask('ble-rx $hex');
    for (final piece in (reply['tx'] as List).cast<String>()) {
      _in.add([
        for (var i = 0; i < piece.length; i += 2)
          int.parse(piece.substring(i, i + 2), radix: 16),
      ]);
    }
  }

  @override
  Future<void> disconnect() async => connected = false;
}

void main() {
  late Directory dir;
  late PyServer py;
  late BobProfile profile;
  late String key, shortId;

  setUpAll(() async {
    dir = Directory.systemTemp.createTempSync('bobBle');
    py = await PyServer.start(dir);
    final pairing = BobClient(host: '127.0.0.1', port: py.port);
    profile = await pairing.pair(await py.code(), "Dart BLE Mac");
    pairing.close();
    final c = BobClient.fromProfile(profile);
    final info = await c.bleKey();
    c.close();
    key = info['key'] as String;
    shortId = info['device'] as String;
  });

  tearDownAll(() async {
    await py.stop();
    dir.deleteSync(recursive: true);
  });

  Future<List<dynamic>> movesNow() async =>
      (await py.ask('handled'))['moves'] as List<dynamic>;

  test(
    'Bob gives the app its key, and the short id is the one the app works out itself',
    () {
      expect(key.length, 64);
      expect(shortId, bleShortId(profile.device));
    },
  );

  test(
    'hello, then drive, stop, the emergency stop, status and commands all work',
    () async {
      final link = BleLink(
        device: shortId,
        key: key,
        transport: PipeTransport(py),
        packetGap: Duration.zero,
      );
      await link.connect();
      expect(link.ready, isTrue);

      await link.drive(0.5, -0.5);
      await link.stop();
      var moves = await movesNow();
      expect(
        moves,
        containsAllInOrder([
          [0.5, -0.5],
          'stop',
        ]),
      );

      final st = await link.status();
      expect(st.keys, containsAll(['e', 'a', 'd', 's']));
      expect(st['s'], '0.80');

      expect(await link.command('/say hi'), 'did /say hi');
      final long = '/say ${'a long sentence ' * 6}'.trim();
      // many packets, put back together on Bob's side (and an answer line is cut at 100 characters, by design)
      expect(await link.command(long), 'did $long'.substring(0, 100));
      expect(await link.command('/quit'), contains("isn't available"));

      await link.estop();
      moves = await movesNow();
      expect(moves.last, 'estop');
      await link.disconnect();
    },
  );

  test('a wrong key is heard but never obeyed', () async {
    final before = (await movesNow()).length;
    final link = BleLink(
      device: shortId,
      key: 'ff' * 32,
      transport: PipeTransport(py),
      packetGap: Duration.zero,
    );
    await link.connect(); // hello only names the device: it works...
    await link.drive(1, 1); // ...but every signed message is refused
    await link.stop();
    expect((await movesNow()).length, before);
    await link.disconnect();
  });

  test('a device Bob does not know cannot connect, and says why', () async {
    final link = BleLink(
      device: 'deadbeef',
      key: key,
      transport: PipeTransport(py),
      packetGap: Duration.zero,
    );
    await expectLater(
      link.connect(),
      throwsA(
        isA<BleException>().having(
          (e) => e.message,
          'message',
          contains("doesn't know this device"),
        ),
      ),
    );
    expect(link.state, 'error');
  });

  test('a device that is unpaired stops being obeyed at once', () async {
    final pairing = BobClient(host: '127.0.0.1', port: py.port);
    final other = await pairing.pair(await py.code(), 'Leaving Phone');
    pairing.close();
    final c = BobClient.fromProfile(other);
    final info = await c.bleKey();
    final link = BleLink(
      device: info['device'] as String,
      key: info['key'] as String,
      transport: PipeTransport(py),
      packetGap: Duration.zero,
    );
    await link.connect();
    await link.drive(0.2, 0.2);
    final before = (await movesNow()).length;
    await c.unpair();
    c.close();
    await link.drive(0.3, 0.3);
    await Future<void>.delayed(const Duration(milliseconds: 200));
    expect((await movesNow()).length, before);
    await link.disconnect();
  });

  test(
    'the app state gets the key by itself, drives and stops over Bluetooth, and sends the emergency stop both ways',
    () async {
      SharedPreferences.setMockInitialValues({});
      final s = AppState(
        pollEvery: const Duration(milliseconds: 100),
        bleTransport: () => PipeTransport(py),
      );
      await s.load();
      await s.setProfile(
        profile,
      ); // paired over Wi-Fi: the key comes with the first successful poll
      final deadline = DateTime.now().add(const Duration(seconds: 10));
      while (!s.bleAvailable && DateTime.now().isBefore(deadline)) {
        await Future<void>.delayed(const Duration(milliseconds: 100));
      }
      expect(s.bleAvailable, isTrue);
      expect(s.profile!.bleDevice, shortId);

      expect(await s.connectBluetooth(), isNull);
      expect(s.usingBluetooth, isTrue);
      await s.drive(0.4, 0.4);
      expect(await movesNow(), anyElement([0.4, 0.4]));

      await s.send('/estop'); // over Bluetooth, and over Wi-Fi too
      await Future<void>.delayed(const Duration(milliseconds: 500));
      expect(await movesNow(), anyElement('estop'));
      final handled = (await py.ask('handled'))['handled'] as List;
      expect(handled.any((h) => (h as List).first == '/estop'), isTrue);

      await s.disconnectBluetooth();
      expect(s.usingBluetooth, isFalse);
      s.dispose();
    },
  );

  test(
    'without a key the app says what to do, and a Bluetooth that cannot start says why',
    () async {
      SharedPreferences.setMockInitialValues({});
      final s = AppState(autoConnect: false);
      await s.load();
      await s.setProfile(profile);
      expect(s.bleAvailable, isFalse);
      expect(
        await s.connectBluetooth(),
        contains('connect over Wi-Fi once first'),
      );
      s.dispose();
    },
  );
}
