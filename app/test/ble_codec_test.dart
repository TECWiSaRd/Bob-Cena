// The Bluetooth message format. The numbers below are the SAME ones tests/test_ble.py checks on Bob's side: if the two ever disagree, one of the
// two tests fails, so the app and Bob cannot drift apart without somebody noticing.
import 'dart:convert';
import 'dart:typed_data';

import 'package:bob_app/src/ble_codec.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final key = [
    for (var i = 0; i < 32; i++) i.toRadixString(16).padLeft(2, '0'),
  ].join();
  const nonce = '0011223344556677';

  test('the short id and the signatures match the ones Bob checks', () {
    final dev = bleShortId("Adam's MacBook");
    expect(dev, 'a1a0a419');
    expect(bleMac(key, dev, nonce, 1, 'D 0.50 -0.50'), 'c28b205c56df1c00');
    expect(bleMac(key, dev, nonce, 2, 'S'), '619b9d570f114191');
    expect(bleMac(key, dev, nonce, 3, 'C /speed 0.3'), '5398eb141d2dff12');
  });

  test('a signed line is built the way Bob reads it', () {
    final dev = bleShortId("Adam's MacBook");
    expect(
      bleSigned(
        dev: dev,
        key: key,
        nonce: nonce,
        ctr: 1,
        cmd: 'D',
        args: '0.50 -0.50',
      ),
      'D a1a0a419 1 0.50 -0.50 c28b205c56df1c00',
    );
    expect(
      bleSigned(dev: dev, key: key, nonce: nonce, ctr: 2, cmd: 'S'),
      'S a1a0a419 2 619b9d570f114191',
    );
    expect(
      bleSigned(
        dev: dev,
        key: key,
        nonce: nonce,
        ctr: 3,
        cmd: 'C',
        args: '/speed 0.3',
      ),
      'C a1a0a419 3 5398eb141d2dff12 /speed 0.3',
    );
  });

  test('speeds are written with two decimals and never as -0.00', () {
    expect(bleNumber(0.5), '0.50');
    expect(bleNumber(-0.5), '-0.50');
    expect(bleNumber(-0.0), '0.00');
    expect(bleNumber(-0.001), '0.00');
    expect(bleNumber(7), '1.00');
    expect(bleNumber(-7), '-1.00');
  });

  test('lines are cut into small packets and put back together', () {
    const text = 'C a1a0a419 7 5398eb141d2dff12 /say hello there, everybody';
    final pieces = bleChunks(text);
    expect(pieces.every((p) => p.length <= bleChunk), isTrue);
    final a = BleLineAssembler();
    final got = <String>[];
    for (final p in pieces) {
      got.addAll(a.feed(p));
    }
    expect(got, [text]);
  });

  test('several lines in one write and a line split anywhere', () {
    final a = BleLineAssembler();
    expect(a.feed(utf8.encode('E\nS x\n')), ['E', 'S x']);
    expect(a.feed(utf8.encode('D a')), isEmpty);
    expect(a.feed(utf8.encode('bc 1\r\n')), ['D abc 1']);
  });

  test('garbage cannot pile up', () {
    final a = BleLineAssembler(limit: 50);
    expect(a.feed(Uint8List.fromList(List.filled(400, 120))), isEmpty);
    expect(a.feed([...List.filled(100, 120), 10, 69, 10]), ['E']);
    var t = DateTime(2026);
    final b = BleLineAssembler(now: () => t);
    b.feed(utf8.encode('half a li'));
    t = t.add(const Duration(seconds: 10));
    expect(b.feed(utf8.encode('E\n')), ['E']);
  });
}
