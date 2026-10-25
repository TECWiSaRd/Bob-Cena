import 'dart:async';
import 'dart:typed_data';

import 'package:bob_app/src/app_state.dart';
import 'package:bob_app/src/client.dart';
import 'package:bob_app/src/home_screen.dart';
import 'package:bob_app/src/profile.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Stands in for Bob: remembers what it was told, and answers status the way a real Bob would after each command.
class FakeBob extends BobClient {
  FakeBob() : super(host: 'x', port: 1);
  final sent = <String>[];
  bool fail = false;
  String answer = '';
  Map<String, dynamic> real = {
    'mode': 'AUTO',
    'auto': true,
    'follow': false,
    'sleep': false,
    'muted': false,
    'camera': 'on',
    'going': false,
    'rooms': ['Kitchen', 'Living Room'],
    'log': [],
    'usage': {},
    'vitals': {},
  };

  @override
  Future<String> command(String text) async {
    sent.add(text);
    if (fail) {
      throw BobApiException(0, "Can't reach Bob");
    }
    switch (text) {
      case '/sleep on':
        real['sleep'] = true;
      case '/sleep off':
        real['sleep'] = false;
      case '/pause':
        real['auto'] = false;
      case '/resume':
        real['auto'] = true;
      case '/mute':
        real['muted'] = true;
      case '/unmute':
        real['muted'] = false;
      case '/camera off':
        real['camera'] = 'OFF';
      case '/camera on':
        real['camera'] = 'on';
      case '/follow 30':
        real['follow'] = true;
      case '/follow off':
        real['follow'] = false;
      case '/estop':
        real['mode'] = 'E-STOP';
        real['auto'] = false;
      case '/clear':
        real['mode'] = 'PAUSED';
      case '/goto Kitchen':
        real['going'] = true;
      case '/goto stop':
        real['going'] = false;
    }
    return answer;
  }

  @override
  Future<Map<String, dynamic>> status() async => Map.of(real);

  @override
  Stream<Uint8List> video() => StreamController<Uint8List>().stream; // a picture that never arrives, and never fails
}

AppState stateWith(FakeBob bob) {
  final s = AppState(autoConnect: false);
  s.loading = false;
  s.profile = BobProfile(
    name: 'Bob',
    host: 'x',
    port: 1,
    fingerprint: 'ab' * 32,
    token: 't',
    device: 'My Mac',
  );
  s.client = bob;
  s.online = true;
  s.status = Map.of(bob.real);
  return s;
}

bool isOn(WidgetTester tester, String key) => tester
    .widget<FilterChip>(
      find.descendant(
        of: find.byKey(Key(key)),
        matching: find.byType(FilterChip),
      ),
    )
    .selected;

Future<void> openMore(WidgetTester tester, AppState s) async {
  tester.view.physicalSize = const Size(1366, 900);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    ChangeNotifierProvider<AppState>.value(
      value: s,
      child: const MaterialApp(home: HomeScreen()),
    ),
  );
  await tester.pump();
  await tester.tap(find.byKey(const Key('nav-more')));
  await tester.pumpAndSettle();
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('AppState.toggle', () {
    test('changes the screen at once, and sends the command', () async {
      final bob = FakeBob();
      final s = stateWith(bob);
      expect(s.sleeping, isFalse);
      final done = s.toggle({'sleep': true}, '/sleep on');
      expect(s.sleeping, isTrue); // before Bob has even answered
      await done;
      expect(bob.sent, ['/sleep on']);
      await s.poll();
      expect(s.sleeping, isTrue); // and Bob agrees
      s.dispose();
    });

    test('flips back if Bob cannot be told', () async {
      final bob = FakeBob()..fail = true;
      final s = stateWith(bob);
      await expectLater(
        s.toggle({'sleep': true}, '/sleep on'),
        throwsA(isA<BobApiException>()),
      );
      expect(s.sleeping, isFalse);
      s.dispose();
    });

    test(
      'Bob has the last word: if he refused, the next status puts the switch right',
      () async {
        final bob = FakeBob();
        final s = stateWith(bob);
        bob.real['mode'] =
            'E-STOP'; // e.g. the AI cannot be resumed while the emergency stop is on
        await s.toggle({'auto': true}, '/ignored-by-the-fake');
        await s.poll();
        expect(
          s.aiOn,
          isTrue,
        ); // the fake keeps auto true; the point is the status is re-read
        expect(s.estop, isTrue);
        s.dispose();
      },
    );
  });

  group('the switches on the More page', () {
    testWidgets('show the real state', (tester) async {
      final bob = FakeBob();
      bob.real['sleep'] = true;
      bob.real['camera'] = 'OFF';
      final s = stateWith(bob);
      await openMore(tester, s);
      expect(isOn(tester, 'toggle-ai'), isTrue);
      expect(isOn(tester, 'toggle-sleep'), isTrue);
      expect(isOn(tester, 'toggle-camera'), isFalse);
      expect(isOn(tester, 'toggle-sound'), isTrue);
      expect(isOn(tester, 'toggle-follow'), isFalse);
      expect(isOn(tester, 'toggle-estop'), isFalse);
      s.dispose();
    });

    testWidgets('one tap flips one switch, and the next tap flips it back', (
      tester,
    ) async {
      final bob = FakeBob();
      final s = stateWith(bob);
      await openMore(tester, s);
      await tester.tap(find.byKey(const Key('toggle-sleep')));
      await tester.pumpAndSettle();
      expect(isOn(tester, 'toggle-sleep'), isTrue);
      await tester.tap(find.byKey(const Key('toggle-sleep')));
      await tester.pumpAndSettle();
      expect(isOn(tester, 'toggle-sleep'), isFalse);
      expect(bob.sent, ['/sleep on', '/sleep off']);
      s.dispose();
    });

    testWidgets('each switch sends the right pair of commands', (tester) async {
      final bob = FakeBob();
      final s = stateWith(bob);
      await openMore(tester, s);
      for (final key in [
        'toggle-ai',
        'toggle-follow',
        'toggle-sound',
        'toggle-camera',
        'toggle-estop',
      ]) {
        await tester.tap(find.byKey(Key(key)));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(Key(key)));
        await tester.pumpAndSettle();
      }
      expect(bob.sent, [
        '/pause',
        '/resume',
        '/follow 30',
        '/follow off',
        '/mute',
        '/unmute',
        '/camera off',
        '/camera on',
        '/estop',
        '/clear',
      ]);
      s.dispose();
    });

    testWidgets(
      'the emergency stop switch is red when on, and switching it on also stops the wheels',
      (tester) async {
        final bob = FakeBob();
        final s = stateWith(bob);
        await openMore(tester, s);
        await tester.tap(find.byKey(const Key('toggle-estop')));
        await tester.pumpAndSettle();
        expect(isOn(tester, 'toggle-estop'), isTrue);
        expect(s.estop, isTrue);
        s.dispose();
      },
    );

    testWidgets('a failed command flips the switch back and says why', (
      tester,
    ) async {
      final bob = FakeBob()..fail = true;
      final s = stateWith(bob);
      await openMore(tester, s);
      await tester.tap(find.byKey(const Key('toggle-sleep')));
      await tester.pumpAndSettle();
      expect(isOn(tester, 'toggle-sleep'), isFalse);
      expect(find.text("Can't reach Bob"), findsWidgets);
      s.dispose();
    });

    testWidgets("Bob's answer is shown", (tester) async {
      final bob = FakeBob()..answer = 'E-stop active - /clear first';
      final s = stateWith(bob);
      await openMore(tester, s);
      await tester.tap(find.byKey(const Key('toggle-ai')));
      await tester.pump();
      expect(find.text('E-stop active - /clear first'), findsOneWidget);
      await tester.pumpAndSettle(const Duration(seconds: 5));
      s.dispose();
    });

    testWidgets('Go becomes Stop while he is on the way, and flips back', (
      tester,
    ) async {
      final bob = FakeBob();
      final s = stateWith(bob);
      await openMore(tester, s);
      await tester.scrollUntilVisible(
        find.byKey(const Key('go-toggle')),
        200,
        scrollable: find.byType(Scrollable).last,
      );
      expect(
        find.descendant(
          of: find.byKey(const Key('go-toggle')),
          matching: find.text('Go'),
        ),
        findsOneWidget,
      );
      await tester.tap(find.byKey(const Key('go-toggle')));
      await tester.pumpAndSettle();
      expect(
        find.descendant(
          of: find.byKey(const Key('go-toggle')),
          matching: find.text('Stop'),
        ),
        findsOneWidget,
      );
      await tester.tap(find.byKey(const Key('go-toggle')));
      await tester.pumpAndSettle();
      expect(bob.sent, ['/goto Kitchen', '/goto stop']);
      expect(
        find.descendant(
          of: find.byKey(const Key('go-toggle')),
          matching: find.text('Go'),
        ),
        findsOneWidget,
      );
      s.dispose();
    });
  });

  testWidgets('the Drive page has just the two switches it needs', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1366, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    final bob = FakeBob();
    final s = stateWith(bob);
    s.client = null; // no camera stream in this test
    await tester.pumpWidget(
      ChangeNotifierProvider<AppState>.value(
        value: s,
        child: const MaterialApp(home: HomeScreen()),
      ),
    );
    await tester.pump();
    await tester.tap(find.byKey(const Key('nav-drive')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('toggle-ai')), findsOneWidget);
    expect(find.byKey(const Key('toggle-follow')), findsOneWidget);
    expect(find.byKey(const Key('toggle-sleep')), findsNothing);
    expect(find.text('Pause AI'), findsNothing); // the old buttons are gone
    s.dispose();
  });
}
