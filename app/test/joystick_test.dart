import 'package:bob_app/src/widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  moreStickTests();
  Future<List<(double, double)>> mount(WidgetTester tester) async {
    final seen = <(double, double)>[];
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ListView(
            key: const Key('page'),
            children: [
              const SizedBox(height: 40),
              Center(child: Joystick(onChanged: (x, y) => seen.add((x, y)))),
              const SizedBox(height: 1500),
            ],
          ),
        ),
      ),
    );
    return seen;
  }

  testWidgets('a touch registers at once, with no drag needed', (tester) async {
    final seen = await mount(tester);
    final c = tester.getCenter(find.byType(Joystick));
    final g = await tester.startGesture(
      c + const Offset(0, -80),
    ); // above centre
    await tester.pump();
    expect(seen, isNotEmpty);
    expect(seen.last.$1, closeTo(0, 0.01));
    expect(seen.last.$2, closeTo(0.8, 0.01)); // forward
    await g.up();
    expect(seen.last, (0.0, 0.0));
  });

  testWidgets('every direction registers, not just a few spots', (
    tester,
  ) async {
    final seen = await mount(tester);
    final c = tester.getCenter(find.byType(Joystick));
    for (final (dx, dy) in [
      (60.0, 0.0),
      (-60.0, 0.0),
      (0.0, 60.0),
      (0.0, -60.0),
      (50.0, -50.0),
      (-50.0, 50.0),
    ]) {
      seen.clear();
      final g = await tester.startGesture(c + Offset(dx, dy));
      await tester.pump();
      expect(seen, isNotEmpty, reason: 'touch at ($dx, $dy)');
      expect(seen.last.$1.sign, dx.sign, reason: 'x at ($dx, $dy)');
      expect(seen.last.$2.sign, (-dy).sign, reason: 'y at ($dx, $dy)');
      await g.up();
    }
  });

  testWidgets('dragging forward moves the stick and does not scroll the page', (
    tester,
  ) async {
    final seen = await mount(tester);
    final scroll = tester.state<ScrollableState>(find.byType(Scrollable));
    final c = tester.getCenter(find.byType(Joystick));
    final g = await tester.startGesture(c);
    await g.moveBy(const Offset(0, -40));
    await tester.pump();
    await g.moveBy(const Offset(0, -40));
    await tester.pump();
    expect(scroll.position.pixels, 0);
    expect(seen.last.$2, greaterThan(0.5));
    await g.up();
    expect(seen.last, (0.0, 0.0));
  });

  testWidgets('a second finger does not take over the stick', (tester) async {
    final seen = await mount(tester);
    final c = tester.getCenter(find.byType(Joystick));
    final a = await tester.startGesture(c + const Offset(0, -60));
    final b = await tester.startGesture(c + const Offset(60, 0));
    await tester.pump();
    expect(seen.last.$1, closeTo(0, 0.01)); // still the first finger
    await b.up();
    expect(
      seen.last.$2,
      greaterThan(0),
    ); // letting go of the second changes nothing
    await a.up();
    expect(seen.last, (0.0, 0.0));
  });

  testWidgets('a resting thumb on the middle reads as stopped', (tester) async {
    final seen = await mount(tester);
    final c = tester.getCenter(find.byType(Joystick));
    final g = await tester.startGesture(c + const Offset(3, -3));
    await tester.pump();
    expect(
      seen.every((s) => s == (0.0, 0.0)),
      isTrue,
    ); // nothing sent, or only "stop"
    await g.up();
  });
}

void moreStickTests() {
  testWidgets('a touch on the square\'s corner is ignored', (tester) async {
    final seen = <(double, double)>[];
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Center(child: Joystick(onChanged: (x, y) => seen.add((x, y)))),
        ),
      ),
    );
    final box = tester.getRect(find.byType(Joystick));
    final g = await tester.startGesture(box.bottomRight - const Offset(4, 4));
    await tester.pump();
    expect(seen, isEmpty);
    await g.up();
    final g2 = await tester.startGesture(box.center + const Offset(0, -70));
    await tester.pump();
    expect(seen, isNotEmpty); // the round pad itself still works
    await g2.up();
  });

  testWidgets('removing the stick while a finger is on it says stop', (
    tester,
  ) async {
    final seen = <(double, double)>[];
    var show = true;
    late StateSetter setOuter;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: StatefulBuilder(
            builder: (context, set) {
              setOuter = set;
              return show
                  ? Joystick(onChanged: (x, y) => seen.add((x, y)))
                  : const SizedBox();
            },
          ),
        ),
      ),
    );
    await tester.startGesture(
      tester.getCenter(find.byType(Joystick)) + const Offset(0, -60),
    );
    await tester.pump();
    expect(seen.last.$2, greaterThan(0));
    setOuter(() => show = false);
    await tester.pump();
    expect(seen.last, (0.0, 0.0));
    // (the finger is left down on purpose: the stick it was on no longer exists)
  });

  testWidgets('a resting thumb sends stop once, not on every move', (
    tester,
  ) async {
    final seen = <(double, double)>[];
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Center(child: Joystick(onChanged: (x, y) => seen.add((x, y)))),
        ),
      ),
    );
    final c = tester.getCenter(find.byType(Joystick));
    final g = await tester.startGesture(c + const Offset(2, 2));
    for (var i = 0; i < 5; i++) {
      await g.moveBy(const Offset(1, 0));
    }
    await g.up();
    expect(seen.where((s) => s == (0.0, 0.0)).length, lessThanOrEqualTo(1));
  });
}
