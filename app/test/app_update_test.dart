import 'dart:convert';
import 'dart:io';

import 'package:bob_app/src/app_state.dart';
import 'package:bob_app/src/app_update.dart';
import 'package:bob_app/src/profile.dart';
import 'package:bob_app/src/tabs.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

Map<String, dynamic> release(String tag) => {
  'tag_name': tag,
  'html_url': 'https://github.com/TECWiSaRd/Bob-Cena/releases/tag/$tag',
  'body': 'Notes',
  'assets': [
    {
      'name': 'Bob-mac.zip',
      'browser_download_url':
          'https://github.com/TECWiSaRd/Bob-Cena/releases/download/$tag/Bob-mac.zip',
    },
    {
      'name': 'Bob-android.apk',
      'browser_download_url':
          'https://github.com/TECWiSaRd/Bob-Cena/releases/download/$tag/Bob-android.apk',
    },
  ],
};

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('the version in the code matches pubspec.yaml', () {
    final line = File(
      'pubspec.yaml',
    ).readAsLinesSync().firstWhere((l) => l.startsWith('version:'));
    expect(line.split(':').last.trim().split('+').first, appVersion);
  });

  test('versions compare as numbers, not text', () {
    expect(isNewer('26.10.3', '26.10.2'), isTrue);
    expect(isNewer('v26.11', '26.10.2'), isTrue);
    expect(isNewer('26.10.10', '26.10.9'), isTrue);
    expect(isNewer('26.10.2', '26.10.2'), isFalse);
    expect(isNewer('26.10.2', '26.10.2.0'), isFalse);
    expect(isNewer('26.10.1', '26.10.2'), isFalse);
    expect(isNewer('nightly', '26.10.2'), isFalse);
    expect(isNewer('26.11', 'dev'), isFalse);
  });

  group('reading GitHub\'s answer', () {
    test('picks the file for this kind of device', () {
      final mac = parseRelease(release('v26.11'), 'Bob-mac.zip')!;
      expect(mac.version, '26.11');
      expect(mac.download.toString(), endsWith('/v26.11/Bob-mac.zip'));
      final android = parseRelease(release('26.11'), 'Bob-android.apk')!;
      expect(android.download.toString(), endsWith('Bob-android.apk'));
      expect(parseRelease(release('26.11'), null)!.download, isNull);
    });

    test('refuses anything odd', () {
      expect(parseRelease('nope', 'x'), isNull);
      expect(parseRelease({'tag_name': 'nightly'}, 'x'), isNull);
      final r = release('26.11')..['html_url'] = 'http://example.com/x';
      expect(parseRelease(r, 'x'), isNull); // not https
      final bad = release('26.11');
      (bad['assets'] as List)[0]['browser_download_url'] = 'http://evil/x.zip';
      expect(parseRelease(bad, 'Bob-mac.zip')!.download, isNull);
    });
  });

  test('fetchLatestRelease asks GitHub and reads the answer', () async {
    HttpOverrides.global =
        null; // the widget test binding would answer every request with 400
    final server = await HttpServer.bind('127.0.0.1', 0);
    final seen = <String>[];
    server.listen((req) {
      seen.add(req.headers.value('user-agent') ?? '');
      req.response
        ..headers.contentType = ContentType.json
        ..write(jsonEncode(release('26.11')));
      req.response.close();
    });
    final http = HttpClient();
    http.findProxy = (_) => 'DIRECT';
    http.connectionFactory = (uri, proxyHost, proxyPort) =>
        Socket.startConnect('127.0.0.1', server.port);
    final r = await fetchLatestRelease(http: http, assetName: 'Bob-mac.zip');
    expect(r!.version, '26.11');
    expect(seen.single, startsWith('bob-app/'));
    http.close(force: true);
    await server.close(force: true);
  });

  group('the button', () {
    AppState state(ReleaseInfo? Function() answer, List<Uri> opened) {
      final s = AppState(
        autoConnect: false,
        fetchRelease: () async => answer(),
        openUrl: (u) async {
          opened.add(u);
          return true;
        },
      );
      s.loading = false;
      s.profile = BobProfile(
        name: 'Bob',
        host: 'x',
        port: 1,
        fingerprint: 'ab' * 32,
        token: 't',
        device: 'Mac',
      );
      return s;
    }

    Future<void> show(WidgetTester tester, AppState s) async {
      tester.view.physicalSize = const Size(1000, 1400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(
        ChangeNotifierProvider<AppState>.value(
          value: s,
          child: const MaterialApp(home: Scaffold(body: UpdateCard())),
        ),
      );
    }

    testWidgets('offers a newer release and opens its download', (
      tester,
    ) async {
      final opened = <Uri>[];
      final s = state(
        () => parseRelease(release('26.99'), 'Bob-mac.zip'),
        opened,
      );
      await show(tester, s);
      expect(find.byKey(const Key('update-download')), findsNothing);
      await tester.tap(find.byKey(const Key('update-check')));
      await tester.pumpAndSettle();
      expect(find.textContaining('26.99 is out'), findsOneWidget);
      await tester.tap(find.byKey(const Key('update-download')));
      await tester.pumpAndSettle();
      expect(opened.single.toString(), endsWith('/26.99/Bob-mac.zip'));
    });

    testWidgets('says so when you are up to date', (tester) async {
      final s = state(
        () => parseRelease(release(appVersion), 'Bob-mac.zip'),
        [],
      );
      await show(tester, s);
      await tester.tap(find.byKey(const Key('update-check')));
      await tester.pumpAndSettle();
      expect(find.textContaining('up to date'), findsOneWidget);
      expect(find.byKey(const Key('update-download')), findsNothing);
    });

    testWidgets('a release with no file opens its page instead', (
      tester,
    ) async {
      final opened = <Uri>[];
      final s = state(() => parseRelease(release('26.99'), 'missing'), opened);
      await show(tester, s);
      await tester.tap(find.byKey(const Key('update-check')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('update-download')));
      await tester.pumpAndSettle();
      expect(opened.single.toString(), contains('/releases/tag/26.99'));
    });

    testWidgets(
      'no network gives a plain message, and a quiet start does not',
      (tester) async {
        final s = AppState(
          autoConnect: false,
          fetchRelease: () async => throw const SocketException('down'),
        );
        await show(tester, s);
        await s.checkForUpdate(quiet: true);
        expect(s.updateProblem, isNull);
        await tester.tap(find.byKey(const Key('update-check')));
        await tester.pumpAndSettle();
        expect(find.textContaining("Can't reach GitHub"), findsOneWidget);
      },
    );
  });
}
