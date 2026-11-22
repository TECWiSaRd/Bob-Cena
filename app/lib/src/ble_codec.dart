import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';

/// The Bluetooth LE message format shared with Bob (blecodec.py on his side describes it; tests on both sides hold the same numbers).
///
/// Messages are text lines ending in a newline, cut into small packets and put back together on the other side.
/// Every message that does something is signed with this device's key, so nobody nearby can drive Bob without it.
const bleService = 'b0b10001-ce17-4c0b-a000-b0b0b0b0b0b0';
const bleRx = 'b0b10002-ce17-4c0b-a000-b0b0b0b0b0b0'; // the app writes here
const bleTx = 'b0b10003-ce17-4c0b-a000-b0b0b0b0b0b0'; // Bob answers here
const bleChunk =
    20; // bytes per radio packet: fits the smallest Bluetooth packet size
const bleMaxLine = 400;

/// The 8 hex digits that stand for a device's name in every message.
String bleShortId(String device) =>
    sha256.convert(utf8.encode(device)).toString().substring(0, 8);

Uint8List _fromHex(String hex) {
  if (hex.length.isOdd) throw const FormatException('odd length key');
  return Uint8List.fromList([
    for (var i = 0; i < hex.length; i += 2)
      int.parse(hex.substring(i, i + 2), radix: 16),
  ]);
}

/// The signature of one message: the first 16 hex digits of HMAC-SHA256 over "dev|nonce|ctr|body".
String bleMac(String keyHex, String dev, String nonce, int ctr, String body) {
  final digest = Hmac(
    sha256,
    _fromHex(keyHex),
  ).convert(utf8.encode('$dev|$nonce|$ctr|$body'));
  return digest.toString().substring(0, 16);
}

/// A line (a newline is added) cut into packets.
List<Uint8List> bleChunks(String text, {int size = bleChunk}) {
  final data = utf8.encode('${text.replaceAll(RegExp(r'\n+$'), '')}\n');
  return [
    for (var i = 0; i < data.length; i += size)
      Uint8List.fromList(
        data.sublist(i, i + size > data.length ? data.length : i + size),
      ),
  ];
}

/// How a speed is written in a drive message: two decimals, never "-0.00" (which would still work, but reads oddly).
String bleNumber(double v) {
  final s = v.clamp(-1.0, 1.0).toStringAsFixed(2);
  return s == '-0.00' ? '0.00' : s;
}

/// A signed message, ready to send. [cmd] is D, S, T, E or C; [args] is "0.30 0.30" for D, the text for C.
String bleSigned({
  required String dev,
  required String key,
  required String nonce,
  required int ctr,
  required String cmd,
  String args = '',
}) {
  final body = switch (cmd) {
    'D' => 'D $args',
    'C' => 'C $args',
    _ => cmd,
  };
  final mac = bleMac(key, dev, nonce, ctr, body);
  return switch (cmd) {
    'D' => 'D $dev $ctr $args $mac',
    'C' => 'C $dev $ctr $mac $args',
    _ => '$cmd $dev $ctr $mac',
  };
}

/// Puts packets back together into lines. A half-finished line that never ends is dropped after a few seconds, and a line that
/// grows too long is thrown away.
class BleLineAssembler {
  BleLineAssembler({
    this.limit = bleMaxLine,
    this.stale = const Duration(seconds: 3),
    DateTime Function()? now,
  }) : _now = now ?? DateTime.now;

  final int limit;
  final Duration stale;
  final DateTime Function() _now;
  final List<int> _buf = [];
  DateTime _last = DateTime.fromMillisecondsSinceEpoch(0);
  bool _skip = false;

  List<String> feed(List<int> data) {
    final now = _now();
    if (_buf.isNotEmpty && now.difference(_last) > stale) _buf.clear();
    _last = now;
    final lines = <String>[];
    for (final byte in data) {
      if (byte == 10) {
        if (!_skip && _buf.isNotEmpty) {
          lines.add(utf8.decode(_buf, allowMalformed: true).trim());
        }
        _buf.clear();
        _skip = false;
      } else if (!_skip) {
        _buf.add(byte);
        if (_buf.length > limit) {
          _buf.clear();
          _skip = true;
        }
      }
    }
    return lines.where((l) => l.isNotEmpty).toList();
  }
}
