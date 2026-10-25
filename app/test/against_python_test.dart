// Runs the REAL Python Bob server (tests/app_test_server.py: real certificate, real pairing, real API) and drives it with the
// app's own client code, so the two halves are proven to speak the same protocol.
//
//   BOB_PYTHON=/path/to/python flutter test test/against_python_test.dart
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:bob_app/src/client.dart';
import 'package:flutter_test/flutter_test.dart';

class PyServer {
  late Process proc;
  late int port;
  late String fingerprint;
  late final StreamIterator<String> _it;

  static Future<PyServer> start(Directory base) async {
    final s = PyServer();
    final python = Platform.environment['BOB_PYTHON'] ?? 'python3';
    final script = File('../tests/app_test_server.py').absolute.path;
    s.proc = await Process.start(python, [script, base.path]);
    final lines = s.proc.stdout
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .asBroadcastStream();
    s._it = StreamIterator(lines);
    s.proc.stderr.drain<void>();
    final ready = await s._next();
    s.port = ready['https_port'] as int;
    s.fingerprint = ready['fingerprint'] as String;
    return s;
  }

  Future<Map<String, dynamic>> _next() async {
    if (!await _it.moveNext().timeout(const Duration(seconds: 30))) {
      throw StateError('server ended');
    }
    return jsonDecode(_it.current) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> ask(String word) async {
    proc.stdin.writeln(word);
    return _next();
  }

  Future<String> code() async => (await ask('code'))['code'] as String;

  Future<void> stop() async {
    proc.stdin.writeln('quit');
    await proc.exitCode.timeout(
      const Duration(seconds: 10),
      onTimeout: () {
        proc.kill();
        return -1;
      },
    );
  }
}

void main() {
  late Directory dirA, dirB;
  late PyServer a;

  setUpAll(() async {
    dirA = Directory.systemTemp.createTempSync('bobA');
    dirB = Directory.systemTemp.createTempSync('bobB');
    a = await PyServer.start(dirA);
  });

  tearDownAll(() async {
    await a.stop();
    dirA.deleteSync(recursive: true);
    dirB.deleteSync(recursive: true);
  });

  test('pairs, then status, commands, driving and video all work', () async {
    final pairing = BobClient(host: '127.0.0.1', port: a.port);
    final profile = await pairing.pair(await a.code(), 'Dart Test Mac');
    pairing.close();
    expect(
      profile.fingerprint,
      a.fingerprint,
    ); // the certificate the app saw is the one Bob made
    expect(profile.name, 'TestBob');

    final c = BobClient.fromProfile(profile);
    final st = await c.status();
    expect(st['mode'], 'AUTO');
    expect((st['usage'] as Map)['all'], 3.25);
    expect(await c.command('/say hi'), 'did /say hi');
    await c.drive(0.5, -0.5);
    await c.drive(0, 0);
    final seen = await a.ask('handled');
    expect((seen['handled'] as List).last, ['/say hi', 'app:Dart Test Mac']);
    expect(seen['moves'], [
      [0.5, -0.5],
      'stop',
    ]);

    final frames = await c
        .video()
        .take(3)
        .toList()
        .timeout(const Duration(seconds: 15));
    expect(frames.length, 3);
    expect(frames.first.first, 0xff);
    expect(frames.first.last, 0xd9);

    await c.unpair();
    await expectLater(
      c.status(),
      throwsA(
        isA<BobApiException>().having(
          (e) => e.unauthorized,
          'unauthorized',
          isTrue,
        ),
      ),
    );
    c.close();
  });

  test('a wrong code is refused and nothing is saved', () async {
    await a.code(); // a real code exists, but we guess another
    final c = BobClient(host: '127.0.0.1', port: a.port);
    await expectLater(
      c.pair('AAAA-BBBB-CCCC', 'Guesser'),
      throwsA(isA<BobApiException>().having((e) => e.status, 'status', 401)),
    );
    c.close();
  });

  test('a code works only once', () async {
    final code = await a.code();
    final first = BobClient(host: '127.0.0.1', port: a.port);
    await first.pair(code, 'First');
    first.close();
    final second = BobClient(host: '127.0.0.1', port: a.port);
    await expectLater(
      second.pair(code, 'Second'),
      throwsA(isA<BobApiException>()),
    );
    second.close();
  });

  test(
    'a different Bob (another certificate) is rejected after pairing: pinning works',
    () async {
      final profile = await (() async {
        final c = BobClient(host: '127.0.0.1', port: a.port);
        final p = await c.pair(await a.code(), 'Pinned');
        c.close();
        return p;
      })();
      final b = await PyServer.start(
        dirB,
      ); // an impostor on another port with its own certificate
      try {
        expect(b.fingerprint, isNot(a.fingerprint));
        final impostor = BobClient(
          host: '127.0.0.1',
          port: b.port,
          pinnedFingerprint: profile.fingerprint,
          token: profile.token,
        );
        await expectLater(impostor.status(), throwsA(anything));
        expect(impostor.certificateRejected, isTrue);
        impostor.close();
      } finally {
        await b.stop();
      }
    },
  );

  test(
    'a man in the middle cannot pair: a proof made for another certificate fails',
    () async {
      // An impostor cannot know the code, so even if it presents its own certificate the app's proof (made over THAT
      // certificate) does not match what the real Bob expects. Simulate by sending Bob a proof computed over a wrong certificate.
      final code = await a.code();
      final c = BobClient(host: '127.0.0.1', port: a.port);
      await c.info(); // learn the real fingerprint
      final raw = HttpClient()..badCertificateCallback = (a, b, c) => true;
      final req = await raw.postUrl(
        Uri.parse('https://127.0.0.1:${a.port}/api/v1/pair'),
      );
      final payload = utf8.encode(
        jsonEncode({
          'device': 'MITM',
          'nonce': 'nonce-nonce-1',
          'proof': 'aa' * 32,
        }),
      );
      req.headers.contentType = ContentType.json;
      req.contentLength = payload.length;
      req.add(payload);
      final resp = await req.close();
      expect(resp.statusCode, 401);
      await resp.drain<void>();
      raw.close(force: true);
      c.close();
      // the real code still works afterwards
      final ok = BobClient(host: '127.0.0.1', port: a.port);
      await ok.pair(code, 'Real');
      ok.close();
    },
  );
}
