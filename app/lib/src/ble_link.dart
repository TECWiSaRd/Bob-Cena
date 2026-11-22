import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:universal_ble/universal_ble.dart';

import 'ble_codec.dart';

/// The radio underneath [BleLink]: find Bob, connect, write to him and hear him back. A fake one is used in tests.
abstract class BleTransport {
  /// Find Bob's Bluetooth service and connect. Throws a [BleException] with a plain sentence if it can't.
  Future<void> connect();

  /// Bytes Bob sent (already one packet at a time).
  Stream<List<int>> get incoming;

  /// Emits false when the link drops.
  Stream<bool> get connection;

  /// Send one packet.
  Future<void> write(Uint8List packet);

  Future<void> disconnect();
}

class BleException implements Exception {
  BleException(this.message);
  final String message;
  @override
  String toString() => message;
}

/// One Bluetooth conversation with Bob: says hello, signs and sends drive pulses, stops, status, commands, and the emergency stop.
///
/// Bob answers "N nonce" to a hello; every later message is signed with the key and counts up, so it can't be forged or replayed.
/// Drive pulses are meant to be repeated about four times a second while a stick is held: Bob stops by himself 0.4 seconds after the last one.
class BleLink extends ChangeNotifier {
  BleLink({
    required this.device,
    required this.key,
    required this.transport,
    this.helloTimeout = const Duration(seconds: 4),
    this.replyTimeout = const Duration(seconds: 3),
    this.packetGap = const Duration(milliseconds: 30),
  });

  final String device; // the 8-hex short id Bob knows this device by
  final String
  key; // this device's Bluetooth key (hex), from Bob over Wi-Fi at pairing time
  final BleTransport transport;
  final Duration helloTimeout;
  final Duration replyTimeout;
  final Duration packetGap;

  /// idle, connecting, hello, ready, lost, or error
  String state = 'idle';
  String? problem;
  Map<String, String> bobStatus = {};

  bool get ready => state == 'ready';

  String? _nonce;
  int _ctr = 0;
  StreamSubscription<List<int>>? _inSub;
  StreamSubscription<bool>? _connSub;
  final _assembler = BleLineAssembler();
  final _lines = StreamController<String>.broadcast();
  final List<String> _outbox = [];
  bool _sending = false;
  bool _closed = false;

  void _set(String s, [String? why]) {
    state = s;
    problem = why;
    if (!_closed) notifyListeners();
  }

  /// Connect and say hello. Returns normally when [ready]; throws [BleException] otherwise (the reason is also in [problem]).
  Future<void> connect() async {
    if (state == 'connecting' || state == 'hello' || ready) return;
    _closed = false;
    _set('connecting');
    try {
      await transport.connect();
      _inSub = transport.incoming.listen((data) {
        for (final line in _assembler.feed(data)) {
          _lines.add(line);
          if (line == 'ERR session' && ready) {
            unawaited(
              _hello().catchError((_) {}),
            ); // Bob forgot us (a restart, a long quiet spell): say hello again
          }
        }
      });
      _connSub = transport.connection.listen((up) {
        if (!up && !_closed && state != 'idle') {
          _outbox.clear();
          _set('lost', 'The Bluetooth link dropped.');
        }
      });
      await _hello();
    } on BleException catch (e) {
      await _cleanup();
      _set('error', e.message);
      rethrow;
    } catch (e) {
      await _cleanup();
      final message = "Bluetooth didn't work: $e";
      _set('error', message);
      throw BleException(message);
    }
  }

  Future<void> _hello() async {
    _set('hello');
    final reply = _waitFor(
      (l) => l.startsWith('N ') || l.startsWith('ERR'),
      helloTimeout,
    );
    await _write('H $device');
    final line = await reply;
    if (line == null) {
      throw BleException(
        "Bob didn't answer. Is Bluetooth control switched on for him ([ble] enabled), and are you close enough?",
      );
    }
    if (!line.startsWith('N ')) {
      throw BleException(
        line.contains('unknown device')
            ? "Bob doesn't know this device for Bluetooth: connect over Wi-Fi once to get its key."
            : 'Bob refused: $line',
      );
    }
    _nonce = line.substring(2).trim();
    _ctr = 0;
    _set('ready');
  }

  /// The next line from Bob that [match] accepts, or null if none arrives in time. Call it BEFORE sending, so the reply can't be missed.
  Future<String?> _waitFor(
    bool Function(String) match,
    Duration timeout,
  ) async {
    final c = Completer<String?>();
    late StreamSubscription<String> sub;
    sub = _lines.stream.listen((l) {
      if (!c.isCompleted && match(l)) c.complete(l);
    });
    Timer(timeout, () {
      if (!c.isCompleted) c.complete(null);
    });
    final result = await c.future;
    await sub.cancel();
    return result;
  }

  // ---- sending: one message at a time, a newer drive pulse replaces one still waiting ----
  Future<void> _write(String line) async {
    for (final packet in bleChunks(line)) {
      await transport.write(packet);
      if (packetGap > Duration.zero) await Future<void>.delayed(packetGap);
    }
  }

  Future<void> _queue(String line, {bool replaceDrive = false}) async {
    if (replaceDrive) _outbox.removeWhere((l) => l.startsWith('D '));
    _outbox.add(line);
    if (_sending) return;
    _sending = true;
    try {
      while (_outbox.isNotEmpty && !_closed) {
        await _write(_outbox.removeAt(0));
      }
    } finally {
      _sending = false;
    }
  }

  String _signed(String cmd, [String args = '']) {
    _ctr++;
    return bleSigned(
      dev: device,
      key: key,
      nonce: _nonce!,
      ctr: _ctr,
      cmd: cmd,
      args: args,
    );
  }

  /// One drive pulse (wheel speeds -1 to 1). Send it again before 0.4 seconds are up to keep going.
  Future<void> drive(double left, double right) async {
    if (!ready) return;
    if (left == 0 && right == 0) return stop();
    await _queue(
      _signed('D', '${bleNumber(left)} ${bleNumber(right)}'),
      replaceDrive: true,
    );
  }

  Future<void> stop() async {
    if (!ready) return;
    _outbox.removeWhere((l) => l.startsWith('D '));
    await _queue(_signed('S'));
  }

  /// The emergency stop. It is sent even when the link isn't signed in, because Bob takes an unsigned one from anyone nearby.
  Future<void> estop() async {
    _outbox.clear();
    try {
      await _write('E');
      if (ready) {
        // and the signed form, for a Bob that doesn't take an open one
        await _write(_signed('E'));
      }
    } catch (_) {}
  }

  /// Bob's status, or an empty map if he doesn't answer.
  Future<Map<String, String>> status() async {
    if (!ready) return bobStatus;
    final reply = _waitFor((l) => l.startsWith('T '), replyTimeout);
    await _queue(_signed('T'));
    final line = await reply;
    if (line != null) {
      bobStatus = {
        for (final part in line.substring(2).split(' '))
          if (part.contains('='))
            part.split('=').first: part.split('=').skip(1).join('='),
      };
      if (!_closed) notifyListeners();
    }
    return bobStatus;
  }

  /// Run a console command (only the ones the app may use over Wi-Fi) and return what he says.
  Future<String> command(String text) async {
    if (!ready) throw BleException('Not connected over Bluetooth.');
    final lines = <String>[];
    final done = Completer<void>();
    late StreamSubscription<String> sub;
    sub = _lines.stream.listen((l) {
      if (l.startsWith('R ')) {
        lines.add(l.substring(2));
      } else if (l == 'OK' || l.startsWith('ERR')) {
        if (l.startsWith('ERR')) lines.add(l);
        if (!done.isCompleted) done.complete();
      }
    });
    await _queue(_signed('C', text));
    // Answers come as R lines; with nothing more to say Bob sends none, so wait a short while after the last.
    var seen = -1;
    final end = DateTime.now().add(replyTimeout);
    while (!done.isCompleted && DateTime.now().isBefore(end)) {
      await Future<void>.delayed(const Duration(milliseconds: 100));
      if (lines.length == seen && lines.isNotEmpty) break;
      seen = lines.length;
    }
    await sub.cancel();
    return lines.join('\n');
  }

  Future<void> _cleanup() async {
    await _inSub?.cancel();
    await _connSub?.cancel();
    _inSub = _connSub = null;
    _outbox.clear();
    try {
      await transport.disconnect();
    } catch (_) {}
  }

  Future<void> disconnect() async {
    _closed = true;
    await _cleanup();
    state = 'idle';
    problem = null;
    notifyListeners();
  }

  @override
  void dispose() {
    _closed = true;
    unawaited(_cleanup());
    _lines.close();
    super.dispose();
  }
}

/// The real radio: finds Bob's service by its number, connects, and subscribes to his answers (the universal_ble plugin; Mac and Android).
class UniversalBleTransport implements BleTransport {
  UniversalBleTransport({this.scanFor = const Duration(seconds: 12)});

  final Duration scanFor;
  String? _id;
  final _in = StreamController<List<int>>.broadcast();
  final _conn = StreamController<bool>.broadcast();
  StreamSubscription<Uint8List>? _valueSub;
  StreamSubscription<bool>? _connSub;

  @override
  Stream<List<int>> get incoming => _in.stream;

  @override
  Stream<bool> get connection => _conn.stream;

  @override
  Future<void> connect() async {
    try {
      final availability = await UniversalBle.getBluetoothAvailabilityState();
      if (availability == AvailabilityState.poweredOff) {
        throw BleException('Bluetooth is switched off on this device.');
      }
      if (availability == AvailabilityState.unauthorized) {
        throw BleException(
          'This app is not allowed to use Bluetooth: allow it in the system settings.',
        );
      }
      if (!await UniversalBle.hasPermissions()) {
        await UniversalBle.requestPermissions();
      }
    } on BleException {
      rethrow;
    } catch (_) {
      // Some platforms can't say: carry on and let the scan tell us.
    }
    final found = Completer<BleDevice?>();
    final sub = UniversalBle.scanStream.listen((d) {
      if (!found.isCompleted &&
          d.services.any((s) => s.toLowerCase() == bleService)) {
        found.complete(d);
      }
    });
    try {
      await UniversalBle.startScan(
        scanFilter: ScanFilter(withServices: [bleService]),
      );
      final dev = await found.future.timeout(scanFor, onTimeout: () => null);
      if (dev == null) {
        throw BleException(
          "Couldn't find Bob over Bluetooth. Is Bluetooth control switched on for him, and are you within a few metres?",
        );
      }
      _id = dev.deviceId;
    } finally {
      await sub.cancel();
      try {
        await UniversalBle.stopScan();
      } catch (_) {}
    }
    final id = _id!;
    _connSub = UniversalBle.connectionStream(id).listen(_conn.add);
    await UniversalBle.connect(id, timeout: const Duration(seconds: 12));
    await UniversalBle.discoverServices(id);
    _valueSub = UniversalBle.characteristicValueStream(
      id,
      bleTx,
      serviceId: bleService,
    ).listen(_in.add);
    await UniversalBle.subscribeNotifications(id, bleService, bleTx);
  }

  @override
  Future<void> write(Uint8List packet) {
    final id = _id;
    if (id == null) throw BleException('Not connected over Bluetooth.');
    return UniversalBle.write(
      id,
      bleService,
      bleRx,
      packet,
      withoutResponse: true,
    );
  }

  @override
  Future<void> disconnect() async {
    await _valueSub?.cancel();
    await _connSub?.cancel();
    _valueSub = _connSub = null;
    final id = _id;
    _id = null;
    if (id != null) {
      try {
        await UniversalBle.disconnect(id);
      } catch (_) {}
    }
  }
}
