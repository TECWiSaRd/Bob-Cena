import 'dart:async';

import 'package:bob_app/src/app_state.dart';
import 'package:bob_app/src/client.dart';
import 'package:bob_app/src/pair_screen.dart';
import 'package:bob_app/src/profile.dart';
import 'package:bob_app/src/tabs.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

class Recorder extends BobClient {
  Recorder() : super(host: 'x', port: 1);
  final moves = <(double, double)>[];
  final sent = <String>[];
  @override
  Future<void> drive(double l, double r) async => moves.add((l, r));
  @override
  Future<String> command(String text) async {
    sent.add(text);
    return '';
  }

  @override
  Stream<Uint8List> video() => StreamController<Uint8List>().stream;
}

AppState stateWith(BobClient c) {
  final s = AppState(autoConnect: false);
  s.loading = false;
  s.profile = BobProfile(
    name: 'Bob',
    host: 'x',
    port: 1,
    fingerprint: 'ab' * 32,
    token: 't',
    device: 'Mac',
  );
  s.client = c;
  s.online = true;
  return s;
}

Future<void> show(WidgetTester tester, AppState s, Widget child) async {
  tester.view.physicalSize = const Size(1000, 1400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    ChangeNotifierProvider<AppState>.value(
      value: s,
      child: MaterialApp(home: Scaffold(body: child)),
    ),
  );
  await tester.pump();
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('address box', () {
    test('accepts the usual forms', () {
      BobAddress a(String t) => parseBobAddress(t);
      expect(
        (a('bobcena.local').host, a('bobcena.local').port),
        ('bobcena.local', 8443),
      );
      expect(a('192.168.1.5:9000').port, 9000);
      expect(a('bob.local:').port, 8443);
      expect(
        (a('[fd00::1]:8443').host, a('[fd00::1]:8443').port),
        ('fd00::1', 8443),
      );
      expect(a('fd00::1').host, 'fd00::1');
      expect(a('fd00::1').port, 8443);
      expect(a('https://bob.local:8443/').host, 'bob.local');
      expect(a('https://bob.local:8443/').port, 8443);
    });

    test('refuses the rest, saying why', () {
      for (final bad in [
        'bob.local:+8443',
        'bob.local:0',
        'bob.local:70000',
        'bob.local:abc',
        'my bob.local',
        'fe80::1%en0',
        '[fd00::1',
        '[fd00::1]x',
        '[bob]:8443',
        ':8443',
        '',
        'bob_local!',
      ]) {
        final r = parseBobAddress(bad);
        expect(r.host, isNull, reason: bad);
        expect(r.error, isNotEmpty, reason: bad);
      }
    });
  });

  group('status values', () {
    test('only finite numbers get through', () {
      expect(statusNumber(3), 3);
      expect(statusNumber('23.5'), 23.5);
      expect(statusNumber(double.nan), isNull);
      expect(statusNumber(double.infinity), isNull);
      expect(statusNumber('NaN'), isNull);
      expect(statusNumber('lots'), isNull);
      expect(statusNumber(null), isNull);
    });

    test('event clock only reads a full date and time', () {
      expect(eventClock('2026-10-25T00:00:00+02:00'), '00:00');
      expect(eventClock('2026-10-25 14:03:09', seconds: true), '14:03:09');
      expect(eventClock('since 5:30'), 'since 5:30');
      expect(eventClock('+02:00'), '+02:00');
    });
  });

  group('polling', () {
    test('a revoked device stops polling', () async {
      final s = stateWith(Recorder());
      s.revoked = true;
      var asked = 0;
      s.client = _Counting(() => asked++);
      await s.poll();
      expect(asked, 0);
      s.dispose();
    });
  });

  group('Drive tab', () {
    testWidgets('leaving a tab that never drove sends nothing', (tester) async {
      final bob = Recorder();
      final s = stateWith(bob);
      await show(tester, s, const DriveTab());
      await tester.pumpWidget(const SizedBox());
      await tester.pump();
      expect(bob.moves, isEmpty);
    });

    testWidgets('leaving a tab that drove stops, even after a release', (
      tester,
    ) async {
      final bob = Recorder();
      final s = stateWith(bob);
      await show(tester, s, const DriveTab());
      await tester.sendKeyDownEvent(LogicalKeyboardKey.keyW);
      await tester.sendKeyUpEvent(LogicalKeyboardKey.keyW);
      expect(bob.moves.last, (0.0, 0.0));
      final before = bob.moves.length;
      await tester.pumpWidget(const SizedBox());
      await tester.pump();
      expect(bob.moves.length, before + 1);
      expect(bob.moves.last, (0.0, 0.0));
    });

    testWidgets('space is an emergency stop and always tells Bob', (
      tester,
    ) async {
      final bob = Recorder();
      final s = stateWith(bob);
      await show(tester, s, const DriveTab());
      await tester.sendKeyDownEvent(LogicalKeyboardKey.keyW);
      await tester.sendKeyDownEvent(LogicalKeyboardKey.space);
      await tester.pump();
      expect(bob.sent, contains('/estop'));
      expect(bob.moves.last, (0.0, 0.0));
      await tester.pumpWidget(const SizedBox());
    });
  });
}

class _Counting extends Recorder {
  _Counting(this.onStatus);
  final void Function() onStatus;
  @override
  Future<Map<String, dynamic>> status() async {
    onStatus();
    return {};
  }
}
