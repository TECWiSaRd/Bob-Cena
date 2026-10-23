import 'dart:typed_data';

import 'package:bob_app/src/mjpeg.dart';
import 'package:bob_app/src/pairing.dart';
import 'package:bob_app/src/profile.dart';
import 'package:bob_app/src/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('pairing proofs match the Python side', () {
    // These values were produced by appapi.py (client_proof / server_proof) for the same inputs.
    const code = 'K7PQ-2M9X-4TWD';
    const nonce = 'abcDEF123_-xyz';
    final fp = 'ab' * 32;
    test('client proof', () {
      expect(clientProof(code, nonce, fp), 'dc9abfc585d2ad3cc47e83c4b8943d3ad7a559473c9edd880f36410e1363df70');
    });
    test('server proof', () {
      expect(serverProof(code, nonce, fp, 'tok_en-123'), '049bd6b9884a2b3734ac36e27d50ec00ee0cd48f1c1797c09160171c6f5d47b0');
    });
    test('typing the code any way works', () {
      expect(clientProof('k7pq2m9x4twd', nonce, fp), clientProof(code, nonce, fp));
      expect(normalizeCode('k7pq-2m9x-4twd'), 'K7PQ2M9X4TWD');
      expect(showCode('k7pq2m9x4twd'), 'K7PQ-2M9X-4TWD');
    });
    test('a different certificate gives a different proof', () {
      expect(clientProof(code, nonce, 'cd' * 32), isNot(clientProof(code, nonce, fp)));
    });
    test('nonces are fresh and url safe', () {
      final a = newNonce(), b = newNonce();
      expect(a, isNot(b));
      expect(RegExp(r'^[A-Za-z0-9_-]+$').hasMatch(a), isTrue);
    });
  });

  group('MjpegParser', () {
    Uint8List part(List<int> jpeg) {
      final head = '--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ${jpeg.length}\r\n\r\n';
      return Uint8List.fromList([...head.codeUnits, ...jpeg, 13, 10]);
    }

    test('one picture', () {
      final jpeg = [0xff, 0xd8, 1, 2, 3, 0xff, 0xd9];
      final frames = MjpegParser().add(part(jpeg));
      expect(frames.length, 1);
      expect(frames.first, jpeg);
    });

    test('pictures split at awkward places and several at once', () {
      final a = List<int>.generate(300, (i) => i % 256), b = List<int>.generate(50, (i) => 255 - i);
      final all = [...part(a), ...part(b)];
      final p = MjpegParser();
      final got = <Uint8List>[];
      for (var i = 0; i < all.length; i += 7) {
        got.addAll(p.add(all.sublist(i, i + 7 > all.length ? all.length : i + 7)));
      }
      expect(got.length, 2);
      expect(got[0], a);
      expect(got[1], b);
    });

    test('a picture containing the boundary text is not cut short', () {
      final tricky = '--frame\r\n\r\n'.codeUnits;
      expect(MjpegParser().add(part(tricky)).single, tricky);
    });

    test('garbage and absurd lengths are survived', () {
      final p = MjpegParser();
      expect(p.add(List<int>.filled(5000, 65)), isEmpty);
      expect(p.add('Content-Length: 99999999999\r\n\r\n'.codeUnits), isEmpty);
      expect(p.add(part([1, 2, 3])).single, [1, 2, 3]); // and it still works afterwards
    });
  });

  group('profile', () {
    test('survives a round trip, and rejects damaged data', () {
      final p = BobProfile(name: 'Bob', host: 'bobcena.local', port: 8443, fingerprint: 'ab' * 32, token: 't', device: 'My Mac');
      final back = BobProfile.fromJson(p.toJson())!;
      expect([back.name, back.host, back.port, back.fingerprint, back.token, back.device],
          ['Bob', 'bobcena.local', 8443, 'ab' * 32, 't', 'My Mac']);
      expect(BobProfile.fromJson({'name': 'x'}), isNull);
      expect(BobProfile.fromJson('nope'), isNull);
      expect(p.copyWith(host: '10.0.0.5').host, '10.0.0.5');
    });
  });

  group('stick mixing', () {
    test('forward, back, spin and arcs never exceed full speed', () {
      expect(mixWheels(0, 1), (1.0, 1.0));
      expect(mixWheels(0, -1), (-1.0, -1.0));
      expect(mixWheels(1, 0), (1.0, -1.0));
      expect(mixWheels(1, 1), (1.0, 0.0));
      final (l, r) = mixWheels(0.8, 0.9);
      expect(l.abs() <= 1 && r.abs() <= 1, isTrue);
      expect(mixWheels(0, 1, scale: 0.5), (0.5, 0.5));
      expect(mixWheels(0, 0), (0.0, 0.0));
    });
  });
}
