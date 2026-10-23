import 'package:bob_app/main.dart';
import 'package:bob_app/src/app_state.dart';
import 'package:bob_app/src/discovery.dart';
import 'package:bob_app/src/home_screen.dart';
import 'package:bob_app/src/pair_screen.dart';
import 'package:bob_app/src/profile.dart';
import 'package:bob_app/src/widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

class QuietDiscovery extends BobDiscovery {
  @override
  Future<void> start() async {}
  @override
  Future<void> stop() async {}
}

Widget wrap(AppState s, Widget child) => ChangeNotifierProvider<AppState>.value(
      value: s,
      child: MaterialApp(home: child),
    );

AppState pairedState({Map<String, dynamic>? status, bool online = true}) {
  final s = AppState(pollEvery: const Duration(hours: 1));
  s.loading = false;
  s.profile = BobProfile(name: 'Bob', host: '127.0.0.1', port: 8443, fingerprint: 'ab' * 32, token: 't', device: 'My Mac');
  s.online = online;
  s.status = status ??
      {
        'mode': 'AUTO', 'thinking': false, 'camera': 'on', 'mic': 'off', 'muted': false, 'cap': 0.8, 'cost': 0.1234,
        'model': 'sonnet-5-5', 'effort': 'low', 'version': '26.11-dev', 'rooms': ['Kitchen', 'Living Room'], 'room': 'Kitchen',
        'usage': {'today': 0.5, 'all': 3.25, 'since': '2026-10-20'},
        'vitals': {'temp_c': 51.2, 'load': 0.4, 'mem_mb': 2000, 'throttled': 0, 'disk_gb': 20.0},
        'events': [{'t': '2026-10-22T18:04:11', 'kind': 'estop', 'text': 'source=console'}],
        'log': [{'l': 'INFO', 't': 'BOB', 'm': 'Hello there'}, {'l': 'ERROR', 't': 'SYS', 'm': 'Something broke'}],
      };
  return s;
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('with nothing paired the app opens on the Add Bob screen', (tester) async {
    await tester.pumpWidget(ChangeNotifierProvider(create: (_) => AppState()..load(), child: const BobApp()));
    await tester.pumpAndSettle();
    expect(find.text('Add Bob'), findsOneWidget);
  });

  testWidgets('pairing checks the address and the code before going anywhere', (tester) async {
    await tester.pumpWidget(wrap(AppState(), PairScreen(discovery: QuietDiscovery())));
    await tester.pump();
    await tester.tap(find.text('Pair'));
    await tester.pump();
    expect(find.textContaining('Choose a Bob from the list'), findsOneWidget);

    await tester.enterText(find.widgetWithText(TextField, 'or type his address'), 'bobcena.local');
    await tester.enterText(find.widgetWithText(TextField, 'pairing code'), 'ABC');
    await tester.tap(find.text('Pair'));
    await tester.pump();
    expect(find.textContaining('12 letters and numbers'), findsOneWidget);
  });

  test('a stored profile is loaded at start', () async {
    SharedPreferences.setMockInitialValues({
      'bob_profile_v1':
          '{"name":"Bob","host":"127.0.0.1","port":1,"fingerprint":"${'ab' * 32}","token":"t","device":"My Mac"}'
    });
    final s = AppState(pollEvery: const Duration(hours: 1));
    await s.load();
    expect(s.profile?.device, 'My Mac');
    expect(s.loading, isFalse);
    await Future<void>.delayed(const Duration(milliseconds: 300)); // its first look at Bob fails: nothing is listening
    expect(s.online, isFalse);
    s.dispose();
  });

  testWidgets('the main screen always shows the emergency stop and the four tabs', (tester) async {
    final s = pairedState();
    await tester.pumpWidget(wrap(s, const HomeScreen()));
    await tester.pump();
    expect(find.text('EMERGENCY STOP'), findsOneWidget);
    for (final t in ['Drive', 'Status', 'Chat', 'More']) {
      expect(find.text(t), findsOneWidget);
    }
    expect(find.text('AUTO'), findsOneWidget);
    s.dispose();
  });

  testWidgets('status tab shows cost, the Pi and recent events', (tester) async {
    final s = pairedState();
    await tester.pumpWidget(wrap(s, const HomeScreen()));
    await tester.tap(find.text('Status'));
    await tester.pumpAndSettle();
    expect(find.text('All time: \$3.25  (since 2026-10-20)'), findsOneWidget);
    expect(find.text('51 °C'), findsOneWidget);
    expect(find.textContaining('estop'), findsWidgets);
    s.dispose();
  });

  testWidgets('chat tab shows the log, and the more tab lists the rooms', (tester) async {
    final s = pairedState();
    await tester.pumpWidget(wrap(s, const HomeScreen()));
    await tester.tap(find.text('Chat'));
    await tester.pumpAndSettle();
    expect(find.text('Hello there'), findsOneWidget);
    expect(find.text('Something broke'), findsOneWidget);
    await tester.tap(find.text('More'));
    await tester.pumpAndSettle();
    expect(find.text('Go to a room'), findsOneWidget);
    expect(find.text('Kitchen'), findsWidgets);
    await tester.scrollUntilVisible(find.text('Unpair this device'), 200, scrollable: find.byType(Scrollable).last);
    expect(find.text('Unpair this device'), findsOneWidget);
    s.dispose();
  });

  testWidgets('when Bob is unreachable or has forgotten this device the screen says so', (tester) async {
    final s = pairedState(online: false)..problem = "Can't reach Bob";
    await tester.pumpWidget(wrap(s, const HomeScreen()));
    await tester.pump();
    expect(find.text("Can't reach Bob"), findsOneWidget);
    expect(find.text('Retry'), findsOneWidget);
    s.revoked = true;
    s.problem = 'Bob no longer recognises this device. Pair it again.';
    s.notifyListeners();
    await tester.pump();
    expect(find.text('Pair again'), findsOneWidget);
    s.dispose();
  });

  testWidgets('the emergency stop banner offers to release it', (tester) async {
    final s = pairedState(status: {'mode': 'E-STOP', 'log': [], 'rooms': []});
    await tester.pumpWidget(wrap(s, const HomeScreen()));
    await tester.pump();
    expect(find.textContaining('Emergency stop is ON'), findsOneWidget);
    expect(find.text('Release'), findsOneWidget);
    s.dispose();
  });

  testWidgets('the stick reports its position and returns to zero when let go', (tester) async {
    final seen = <(double, double)>[];
    await tester.pumpWidget(MaterialApp(home: Center(child: Joystick(onChanged: (x, y) => seen.add((x, y))))));
    final centre = tester.getCenter(find.byType(Joystick));
    final g = await tester.startGesture(centre);
    await g.moveTo(centre + const Offset(0, -100)); // straight up, to the edge
    await g.moveTo(centre + const Offset(300, 0)); // far to the right: clamped to the edge
    await g.up();
    expect(seen.any((p) => p.$2 > 0.95 && p.$1.abs() < 0.05), isTrue);
    expect(seen.any((p) => p.$1 > 0.95), isTrue);
    expect(seen.every((p) => p.$1 * p.$1 + p.$2 * p.$2 <= 1.0001), isTrue);
    expect(seen.last, (0.0, 0.0));
  });
}
