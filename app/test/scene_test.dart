import 'package:bob_app/src/app_state.dart';
import 'package:bob_app/src/home_screen.dart';
import 'package:bob_app/src/profile.dart';
import 'package:bob_app/src/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

const laptop = Size(1366, 768);
const peach = Color(0xFFFFE6CB);

AppState state() {
  final s = AppState(autoConnect: false);
  s.loading = false;
  s.profile = BobProfile(
    name: 'Bob',
    host: 'x',
    port: 1,
    fingerprint: 'ab' * 32,
    token: 't',
    device: "Adam's Mac",
  );
  s.online = true;
  s.status = {
    'mode': 'AUTO',
    'thinking': false,
    'camera': 'on',
    'cost': 0.1,
    'rooms': ['Kitchen'],
    'room': null,
    'usage': {'today': 0.5, 'all': 3.25},
    'vitals': {'temp_c': 51.2, 'load': 0.4, 'mem_mb': 2000},
    'operators': [
      {'name': 'kai', 'via': 'console'},
      {'name': "Adam's Mac", 'via': 'app'},
    ],
    'events': [
      {'t': '2026-10-23T18:04:11', 'kind': 'estop', 'text': 'source=console'},
      {'t': '2026-10-23T18:09:40', 'kind': 'manual_move', 'text': 'left=0.5'},
    ],
    'log': [
      {'l': 'INFO', 't': 'HEARD', 'm': 'hey bob'},
      {'l': 'INFO', 't': 'BOB', 'm': 'I can see the kitchen from here.'},
    ],
  };
  return s;
}

Future<AppState> open(
  WidgetTester tester, {
  Size size = laptop,
  Brightness brightness = Brightness.light,
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  final s = state();
  await tester.pumpWidget(
    ChangeNotifierProvider<AppState>.value(
      value: s,
      child: MaterialApp(theme: bobTheme(brightness), home: const HomeScreen()),
    ),
  );
  await tester.pump();
  return s;
}

Offset iconAt(WidgetTester tester, String id) =>
    tester.getCenter(find.byKey(Key('nav-$id')));

ScrollController controllerOf(WidgetTester tester) => tester
    .widget<CustomScrollView>(find.byKey(const Key('scene-scroll')))
    .controller!;

Future<void> scrollTo(WidgetTester tester, double pixels) async {
  await tester.drag(
    find.byKey(const Key('scene-scroll')),
    Offset(0, -pixels),
    warnIfMissed: false,
  );
  await tester.pumpAndSettle();
}

Rect rect(WidgetTester tester, String key) =>
    tester.getRect(find.byKey(Key(key)));

/// The box that paints a whole screen: the peach one is the fading background, the white one a plain colour.
Rect screenOf(WidgetTester tester, Color color) => color == peach
    ? tester.getRect(find.byKey(const Key('page-one-background')))
    : tester.getRect(
        find
            .byWidgetPredicate((w) => w is ColoredBox && w.color == color)
            .first,
      );

LinearGradient fadeOf(WidgetTester tester) =>
    (tester
                    .widget<DecoratedBox>(
                      find.byKey(const Key('page-one-background')),
                    )
                    .decoration
                as BoxDecoration)
            .gradient!
        as LinearGradient;

void main() {
  testWidgets(
    'at the top: the welcome page, the icons along the bottom, the second screen waiting below',
    (tester) async {
      final s = await open(tester);
      expect(rect(tester, 'pill-mode').top, inInclusiveRange(0, laptop.height));
      expect(
        rect(tester, 'card-tasks').top,
        greaterThanOrEqualTo(laptop.height),
      );
      final ys = [
        'drive',
        'status',
        'chat',
        'more',
      ].map((id) => iconAt(tester, id).dy).toList();
      expect(
        ys.every((y) => (y - ys.first).abs() < 1),
        isTrue,
        reason: 'one row',
      );
      expect(
        ys.first,
        greaterThan(laptop.height - 100),
        reason: 'at the bottom',
      );
      final xs = [
        'drive',
        'status',
        'chat',
        'more',
      ].map((id) => iconAt(tester, id).dx).toList();
      expect(xs, [...xs]..sort());
      s.dispose();
    },
  );

  testWidgets(
    'scrolled down: the icons have flowed out to the edges, as in the second design',
    (tester) async {
      final s = await open(tester);
      await scrollTo(tester, 3000);
      final w = laptop.width, h = laptop.height;
      Offset frac(String id) =>
          Offset(iconAt(tester, id).dx / w, iconAt(tester, id).dy / h);
      expect(frac('drive').dx, closeTo(0.097, 0.02));
      expect(frac('drive').dy, closeTo(0.39, 0.02));
      expect(frac('status').dx, closeTo(0.245, 0.02));
      expect(frac('status').dy, closeTo(0.143, 0.02));
      expect(frac('chat').dx, closeTo(0.763, 0.02));
      expect(frac('chat').dy, closeTo(0.14, 0.02));
      expect(frac('more').dx, closeTo(0.915, 0.02));
      expect(frac('more').dy, closeTo(0.39, 0.02));
      s.dispose();
    },
  );

  testWidgets(
    'scrolled down: the three cards are where the design puts them, and the welcome page has scrolled away',
    (tester) async {
      final s = await open(tester);
      await scrollTo(tester, 3000);
      expect(rect(tester, 'pill-mode').bottom, lessThan(0));
      expect(find.text('I can see the kitchen from here.'), findsOneWidget);
      expect(find.text('kai · console'), findsOneWidget);
      expect(find.text("Adam's Mac · app"), findsOneWidget);
      expect(find.textContaining('manual_move'), findsOneWidget);
      expect(find.textContaining('estop'), findsWidgets);
      final centre = tester.getCenter(find.byKey(const Key('card-something')));
      expect(centre.dx, closeTo(laptop.width * 0.5, 2));
      expect(centre.dy, closeTo(laptop.height * 0.407, 2));
      expect(
        tester.getCenter(find.byKey(const Key('card-operators'))).dx,
        closeTo(laptop.width * 0.234, 2),
      );
      expect(
        tester.getCenter(find.byKey(const Key('card-operators'))).dy,
        closeTo(laptop.height * 0.708, 2),
      );
      expect(
        tester.getCenter(find.byKey(const Key('card-tasks'))).dx,
        closeTo(laptop.width * 0.772, 2),
      );
      s.dispose();
    },
  );

  testWidgets(
    'it really scrolls: both screens move up by exactly as much as you scroll',
    (tester) async {
      final s = await open(tester);
      final controller = controllerOf(tester);
      final pill0 = rect(tester, 'pill-cost').top;
      expect(screenOf(tester, peach).top, 0);
      expect(
        screenOf(tester, Colors.white).top,
        laptop.height,
      ); // the white screen starts exactly where the peach one ends
      controller.jumpTo(200);
      await tester.pump();
      expect(rect(tester, 'pill-cost').top, closeTo(pill0 - 200, 0.5));
      expect(screenOf(tester, peach).top, closeTo(-200, 0.5));
      expect(
        screenOf(tester, Colors.white).top,
        closeTo(laptop.height - 200, 0.5),
      );
      controller.jumpTo(laptop.height);
      await tester.pump();
      expect(
        screenOf(tester, Colors.white).top,
        closeTo(0, 0.5),
      ); // the white screen now fills the window
      expect(screenOf(tester, peach).bottom, closeTo(0, 0.5));
      s.dispose();
    },
  );

  testWidgets(
    'nothing fades: every piece of the page is fully opaque the whole way',
    (tester) async {
      final s = await open(tester);
      final controller = controllerOf(tester);
      for (final f in [0.0, 0.3, 0.6, 1.0]) {
        controller.jumpTo(laptop.height * f);
        await tester.pump();
        for (final key in ['pill-mode', 'card-something', 'card-tasks']) {
          expect(
            find.ancestor(
              of: find.byKey(Key(key)),
              matching: find.byType(Opacity),
            ),
            findsNothing,
            reason: '$key at $f',
          );
        }
      }
      s.dispose();
    },
  );

  testWidgets(
    'the cards slide in a little staggered: the lower two arrive after the middle one',
    (tester) async {
      final s = await open(tester);
      final controller = controllerOf(tester);
      controller.jumpTo(laptop.height * 0.5);
      await tester.pump();
      final middleGap =
          rect(tester, 'card-something').top -
          (laptop.height * 0.407 - rect(tester, 'card-something').height / 2);
      final lowerGap =
          rect(tester, 'card-tasks').top -
          (laptop.height * 0.708 - rect(tester, 'card-tasks').height / 2);
      expect(
        lowerGap,
        greaterThan(middleGap),
      ); // still further down than where it will rest, so it lands later
      controller.jumpTo(laptop.height);
      await tester.pump();
      expect(
        rect(tester, 'card-tasks').center.dy,
        closeTo(laptop.height * 0.708, 1),
      );
      s.dispose();
    },
  );

  testWidgets(
    'it moves smoothly: half way down, an icon is between the two layouts',
    (tester) async {
      final s = await open(tester);
      final start = iconAt(tester, 'drive');
      final controller = controllerOf(tester);
      controller.jumpTo(laptop.height * 0.5);
      await tester.pump();
      final middle = iconAt(tester, 'drive');
      controller.jumpTo(laptop.height);
      await tester.pump();
      final end = iconAt(tester, 'drive');
      expect(middle.dy, lessThan(start.dy));
      expect(middle.dy, greaterThan(end.dy));
      expect(
        middle.dx,
        lessThan(start.dx),
      ); // it curves out a little to the side on the way, rather than a straight line
      s.dispose();
    },
  );

  testWidgets('let go half way and it finishes by itself, to the nearer end', (
    tester,
  ) async {
    final s = await open(tester);
    final controller = controllerOf(tester);
    final travel = laptop.height;
    await scrollTo(tester, travel * 0.3);
    expect(controller.offset, closeTo(0, 1));
    await scrollTo(tester, travel * 0.8);
    expect(controller.offset, closeTo(travel, 1));
    s.dispose();
  });

  testWidgets('the icons still work when they have moved', (tester) async {
    final s = await open(tester);
    await scrollTo(tester, 3000);
    await tester.tap(find.byKey(const Key('nav-chat')));
    await tester.pumpAndSettle();
    expect(find.textContaining('Welcome back'), findsNothing);
    expect(find.byKey(const Key('wordmark')), findsOneWidget);
    s.dispose();
  });

  testWidgets(
    'the emergency stop stays on screen the whole way, and drops lower as the icons leave',
    (tester) async {
      final s = await open(tester);
      final before = tester.getCenter(find.byKey(const Key('estop'))).dy;
      await scrollTo(tester, 3000);
      final after = tester.getCenter(find.byKey(const Key('estop'))).dy;
      expect(find.byKey(const Key('estop')), findsOneWidget);
      expect(after, greaterThan(before));
      expect(after, lessThan(laptop.height));
      s.dispose();
    },
  );

  testWidgets('tapping a pill at the top still opens Status', (tester) async {
    final s = await open(tester);
    await tester.tap(find.byKey(const Key('pill-cost')));
    await tester.pumpAndSettle();
    expect(find.text('What Claude has cost'), findsOneWidget);
    s.dispose();
  });

  testWidgets('in dark mode the second screen is the dark surface, not white', (
    tester,
  ) async {
    final s = await open(tester, brightness: Brightness.dark);
    await scrollTo(tester, 3000);
    final boxes = tester
        .widgetList<ColoredBox>(find.byType(ColoredBox))
        .map((b) => b.color)
        .toList();
    expect(boxes.contains(BobColors.darkSurface), isTrue);
    expect(boxes.contains(Colors.white), isFalse);
    s.dispose();
  });

  testWidgets('a phone: three cards fit side by side and nothing overflows', (
    tester,
  ) async {
    final s = await open(tester, size: const Size(390, 844));
    await scrollTo(tester, 3000);
    final a = rect(tester, 'card-operators');
    final b = rect(tester, 'card-tasks');
    final c = rect(tester, 'card-something');
    expect(a.overlaps(b), isFalse);
    expect(c.bottom, lessThanOrEqualTo(a.top + 1));
    expect(a.left, greaterThanOrEqualTo(0));
    expect(b.right, lessThanOrEqualTo(390));
    for (final id in ['drive', 'status', 'chat', 'more']) {
      expect(iconAt(tester, id).dx, inInclusiveRange(20, 370));
    }
    expect(tester.takeException(), isNull);
    s.dispose();
  });

  testWidgets('with Bob offline the cards say so instead of showing old news', (
    tester,
  ) async {
    final s = await open(tester);
    s.online = false;
    s.status = {};
    s.notifyListeners();
    await tester.pump();
    await scrollTo(tester, 3000);
    expect(find.text('I can see the kitchen from here.'), findsNothing);
    expect(find.text('—'), findsWidgets);
    s.dispose();
  });

  testWidgets('the fade from peach to white is long, eased and has no edge', (
    tester,
  ) async {
    final s = await open(tester);
    final g = fadeOf(tester);
    expect(g.colors.first, peach);
    expect(g.colors.last, Colors.white);
    expect(
      g.stops!.length,
      greaterThanOrEqualTo(12),
    ); // many small steps, not two or three
    expect(g.stops!.first, 0.0);
    expect(g.stops![1], closeTo(0.55, 0.001)); // flat peach for the top half...
    expect(g.colors[1], peach);
    expect(
      g.stops!.last,
      1.0,
    ); // ...then a change spread over the bottom 45% of the screen (about 345 px here)
    // how far each step moves from peach towards white (using the blue channel, which changes most evenly)
    final total = Colors.white.b - peach.b;
    final steps = [
      for (var i = 1; i < g.colors.length; i++)
        (g.colors[i].b - g.colors[i - 1].b) / total,
    ];
    expect(
      steps.every((d) => d >= -0.0001),
      isTrue,
      reason: 'never goes backwards',
    );
    expect(
      steps.reduce((a, b) => a > b ? a : b),
      lessThan(0.16),
      reason: 'no big jump anywhere',
    );
    expect(steps[1], lessThan(0.02), reason: 'starts gently');
    expect(steps.last, lessThan(0.02), reason: 'ends gently');
    s.dispose();
  });

  testWidgets(
    'nothing sits on top of the cards to wash them out: only the one background gradient exists',
    (tester) async {
      final s = await open(tester);
      final gradients = find.byWidgetPredicate(
        (w) =>
            w is DecoratedBox &&
            w.decoration is BoxDecoration &&
            (w.decoration as BoxDecoration).gradient != null,
      );
      expect(gradients, findsOneWidget);
      // the pills are drawn above it, still pure white at the top of the page
      expect(
        find.descendant(
          of: find.byKey(const Key('pill-mode')),
          matching: find.byType(Material),
        ),
        findsWidgets,
      );
      s.dispose();
    },
  );
}
