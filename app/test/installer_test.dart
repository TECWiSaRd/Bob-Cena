import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:bob_app/src/app_state.dart';
import 'package:bob_app/src/app_update.dart';
import 'package:bob_app/src/installer.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class FakeInstaller implements AppInstaller {
  File? got;
  Object? fail;
  @override
  Future<void> install(File file) async {
    if (fail != null) throw fail!;
    got = file;
  }
}

ReleaseInfo release({String? sha}) => ReleaseInfo(
  version: '99.0.0',
  page: Uri.parse('https://github.com/x/y/releases/tag/99'),
  download: Uri.parse('https://github.com/x/y/releases/download/99/Bob.apk'),
  sha256: sha,
);

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    HttpOverrides.global = null;
  });

  group('finding the app', () {
    test('the app folder is found from the running program', () {
      expect(
        appBundleFor('/Applications/Bob.app/Contents/MacOS/Bob'),
        '/Applications/Bob.app',
      );
      expect(appBundleFor('/usr/local/bin/dart'), isNull);
    });
  });

  group('the Mac swap script', () {
    late Directory dir;
    setUp(() => dir = Directory.systemTemp.createTempSync('bob-swap-test'));
    tearDown(() => dir.deleteSync(recursive: true));

    Future<ProcessResult> runSwap(String oldApp, String newApp) {
      final work = Directory('${dir.path}/work')..createSync();
      final f = File('${work.path}/swap.sh')
        ..writeAsStringSync(
          macSwapScript(
            pid: 999999, // no such process: the script goes straight ahead
            oldApp: oldApp,
            newApp: newApp,
            workDir: work.path,
            relaunch: false,
          ),
        );
      return Process.run('/bin/sh', [f.path]);
    }

    test(
      'puts the new app where the old one was, with a space in the path',
      () async {
        final old = Directory('${dir.path}/Apps Folder/Bob.app')
          ..createSync(recursive: true);
        File('${old.path}/version').writeAsStringSync('old');
        final fresh = Directory('${dir.path}/work/Bob.app')
          ..createSync(recursive: true);
        File('${fresh.path}/version').writeAsStringSync('new');
        final r = await runSwap(old.path, fresh.path);
        expect(r.exitCode, 0, reason: '${r.stderr}');
        expect(File('${old.path}/version').readAsStringSync(), 'new');
        expect(Directory('${old.path}.old').existsSync(), isFalse);
        expect(Directory('${dir.path}/work').existsSync(), isFalse);
      },
    );

    test('puts the old app back if the new one cannot be moved in', () async {
      final old = Directory('${dir.path}/Bob.app')..createSync();
      File('${old.path}/version').writeAsStringSync('old');
      final r = await runSwap(old.path, '${dir.path}/work/missing.app');
      expect(r.exitCode, 0);
      expect(File('${old.path}/version').readAsStringSync(), 'old');
    });
  });

  group('downloading', () {
    late Directory dir;
    late HttpServer server;
    late HttpClient client;
    final body = Uint8List.fromList(List.generate(300000, (i) => i % 251));

    setUp(() async {
      dir = Directory.systemTemp.createTempSync('bob-dl-test');
      final pem = await Process.run('openssl', [
        'req',
        '-x509',
        '-newkey',
        'rsa:2048',
        '-nodes',
        '-days',
        '1',
        '-subj',
        '/CN=localhost',
        '-keyout',
        '${dir.path}/k.pem',
        '-out',
        '${dir.path}/c.pem',
      ]);
      expect(pem.exitCode, 0, reason: '${pem.stderr}');
      final ctx = SecurityContext()
        ..useCertificateChain('${dir.path}/c.pem')
        ..usePrivateKey('${dir.path}/k.pem');
      server = await HttpServer.bindSecure('127.0.0.1', 0, ctx);
      server.listen((req) {
        if (req.uri.path == '/missing') {
          req.response.statusCode = 404;
        } else {
          req.response.add(body);
        }
        req.response.close();
      });
      client = HttpClient()..badCertificateCallback = (_, _, _) => true;
    });
    tearDown(() async {
      client.close(force: true);
      await server.close(force: true);
      dir.deleteSync(recursive: true);
    });

    Uri url(String p) => Uri.parse('https://127.0.0.1:${server.port}$p');

    test('saves the file, reports progress and checks the checksum', () async {
      final seen = <double>[];
      final dest = File('${dir.path}/out.bin');
      await downloadFile(
        url('/f'),
        dest,
        sha256Hex: sha256.convert(body).toString().toUpperCase(),
        onProgress: seen.add,
        http: client,
      );
      expect(dest.readAsBytesSync(), body);
      expect(seen.last, 1);
      expect(File('${dest.path}.part').existsSync(), isFalse);
    });

    test(
      'throws away a file that does not match the published checksum',
      () async {
        final dest = File('${dir.path}/out.bin');
        await expectLater(
          downloadFile(url('/f'), dest, sha256Hex: 'ab' * 32, http: client),
          throwsA(isA<UpdateException>()),
        );
        expect(dest.existsSync(), isFalse);
        expect(File('${dest.path}.part').existsSync(), isFalse);
      },
    );

    test('a missing file and a plain http address are refused', () async {
      final dest = File('${dir.path}/out.bin');
      await expectLater(
        downloadFile(url('/missing'), dest, http: client),
        throwsA(isA<UpdateException>()),
      );
      await expectLater(
        downloadFile(Uri.parse('http://example.com/x'), dest),
        throwsA(isA<UpdateException>()),
      );
    });
  });

  group('the release answer', () {
    test('picks up the checksum GitHub publishes for the file', () {
      final r = parseRelease({
        'tag_name': 'v27.1',
        'html_url': 'https://github.com/x/y/releases/tag/v27.1',
        'assets': [
          {
            'name': 'Bob-android.apk',
            'browser_download_url': 'https://github.com/x/y/a.apk',
            'digest': 'sha256:${'AB' * 32}',
          },
        ],
      }, 'Bob-android.apk');
      expect(r!.sha256, 'ab' * 32);
      final none = parseRelease({
        'tag_name': 'v27.1',
        'html_url': 'https://github.com/x/y/releases/tag/v27.1',
        'assets': [
          {
            'name': 'Bob-android.apk',
            'browser_download_url': 'https://github.com/x/y/a.apk',
            'digest': 'md5:nope',
          },
        ],
      }, 'Bob-android.apk');
      expect(none!.sha256, isNull);
    });
  });

  group('AppState.installUpdate', () {
    late Directory dir;
    setUp(() => dir = Directory.systemTemp.createTempSync('bob-state-test'));
    tearDown(() => dir.deleteSync(recursive: true));

    AppState make(
      FakeInstaller? inst, {
      List<String>? log,
      Future<void> Function(Uri, File, String?, void Function(double))? dl,
      List<Uri>? opened,
    }) => AppState(
      autoConnect: false,
      installer: inst,
      selfInstall: inst != null,
      downloadDir: dir,
      fetchRelease: () async => release(sha: 'cd' * 32),
      openUrl: (u) async {
        opened?.add(u);
        return true;
      },
      download:
          dl ??
          (u, f, sum, tick) async {
            log?.add('sum=$sum');
            tick(.5);
            f.writeAsStringSync('apk');
            tick(1);
          },
    );

    test('downloads, then hands the file to the installer', () async {
      final inst = FakeInstaller();
      final log = <String>[];
      final s = make(inst, log: log);
      await s.checkForUpdate();
      expect(await s.installUpdate(), isNull);
      expect(log, ['sum=${'cd' * 32}']);
      expect(inst.got!.path, '${dir.path}/Bob.apk');
      expect(s.updateStage, 'idle');
    });

    test('says what went wrong, and goes back to idle', () async {
      final inst = FakeInstaller()..fail = UpdateException('Nope.');
      final s = make(inst);
      await s.checkForUpdate();
      expect(await s.installUpdate(), 'Nope.');
      expect(s.updateStage, 'idle');
      final s2 = make(
        FakeInstaller(),
        dl: (u, f, sum, tick) async => throw const SocketException('offline'),
      );
      await s2.checkForUpdate();
      expect(await s2.installUpdate(), contains("didn't work"));
      expect(s2.updateStage, 'idle');
    });

    test('shows download progress while it runs', () async {
      final gate = Completer<void>();
      final s = make(
        FakeInstaller(),
        dl: (u, f, sum, tick) async {
          tick(.25);
          await gate.future;
          f.writeAsStringSync('x');
        },
      );
      await s.checkForUpdate();
      final run = s.installUpdate();
      await Future<void>.delayed(Duration.zero);
      expect(s.updateStage, 'downloading');
      expect(s.updateProgress, .25);
      expect(await s.installUpdate(), isNull); // a second tap does nothing
      gate.complete();
      await run;
      expect(s.updateStage, 'idle');
    });

    test(
      'a device that cannot install itself still opens the browser',
      () async {
        final opened = <Uri>[];
        final s = make(null, opened: opened);
        await s.checkForUpdate();
        expect(s.canInstallHere, isFalse);
        expect(await s.installUpdate(), isNull);
        expect(opened.single.path, endsWith('Bob.apk'));
      },
    );
  });
}
