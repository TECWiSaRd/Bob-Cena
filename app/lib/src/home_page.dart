import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'app_state.dart';
import 'design.dart';

/// Where the four navigation icons sit as a fraction of the screen once the page has scrolled (see the second design
/// reference): gamepad left, gauge top-left, chat top-right, sliders right.
const _iconEnds = [
  Offset(0.097, 0.39),
  Offset(0.245, 0.143),
  Offset(0.763, 0.14),
  Offset(0.915, 0.39),
];

/// A vertical fade from [from] to [to] that starts gently and ends gently. The colour is eased (a "smootherstep" curve) and
/// sampled at many points, so it has no visible start or end and no banding. The first [start] of the height stays [from].
LinearGradient softFade(
  Color from,
  Color to, {
  double start = 0.55,
  int steps = 16,
}) {
  final colors = <Color>[from];
  final stops = <double>[0.0];
  for (var i = 0; i <= steps; i++) {
    final t = i / steps;
    final eased = t * t * t * (t * (t * 6 - 15) + 10);
    colors.add(Color.lerp(from, to, eased)!);
    stops.add(start + (1 - start) * t);
  }
  return LinearGradient(
    begin: Alignment.topCenter,
    end: Alignment.bottomCenter,
    colors: colors,
    stops: stops,
  );
}

/// The landing page, as a small scene driven by scrolling.
///
/// At the top it is the welcome page with three info pills and the icon bar along the bottom. Scrolling down really scrolls: the welcome
/// page slides up and away and a second, white screen slides up behind it with three rounded cards (what he just said, who is on, what
/// happened recently), while the four icons glide from the bottom bar out to the edges of the screen.
class HomePage extends StatefulWidget {
  const HomePage({
    super.key,
    required this.items,
    required this.selected,
    required this.onSelect,
    required this.progress,
    this.onOpen,
  });
  final List<NavItem> items;
  final int? selected;
  final void Function(int index) onSelect;
  final ValueNotifier<double>
  progress; // 0 = top of the page, 1 = scrolled all the way; the stop button follows it
  final void Function(int tab)? onOpen; // a tap on a pill (1 = Status)

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  final _scroll = ScrollController();
  double _travel = 1;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(_report);
  }

  void _report() {
    final p = _scroll.hasClients
        ? (_scroll.offset / _travel).clamp(0.0, 1.0)
        : 0.0;
    if (p != widget.progress.value) {
      widget.progress.value = p;
    }
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  bool _settle(ScrollNotification n) {
    // let go half way and it finishes the move by itself, so the page is never left between two designs
    if (n is ScrollEndNotification && _scroll.hasClients) {
      final p = _scroll.offset / _travel;
      if (p > 0.001 && p < 0.999) {
        // not from inside the notification: the scroll is still ending, and a move started now would be dropped
        Future.microtask(() {
          if (_scroll.hasClients &&
              !_scroll.position.isScrollingNotifier.value) {
            _scroll.animateTo(
              p < 0.5 ? 0 : _travel,
              duration: const Duration(milliseconds: 280),
              curve: Curves.easeOut,
            );
          }
        });
      }
    }
    return false;
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    return LayoutBuilder(
      builder: (context, box) {
        final w = box.maxWidth, h = box.maxHeight;
        _travel = math.max(
          1.0,
          h,
        ); // one screen of scrolling: the second screen then sits exactly where the design has it
        return NotificationListener<ScrollNotification>(
          onNotification: _settle,
          child: CustomScrollView(
            key: const Key('scene-scroll'),
            controller: _scroll,
            slivers: [
              SliverPersistentHeader(
                pinned: true,
                delegate: _Scene(
                  height: h,
                  builder: (ctx) => AnimatedBuilder(
                    animation: _scroll,
                    builder: (ctx, _) {
                      final p = _scroll.hasClients
                          ? (_scroll.offset / _travel).clamp(0.0, 1.0)
                          : 0.0;
                      return _buildScene(ctx, s, w, h, p);
                    },
                  ),
                ),
              ),
              SliverToBoxAdapter(child: SizedBox(height: _travel)),
            ],
          ),
        );
      },
    );
  }

  Widget _buildScene(
    BuildContext context,
    AppState s,
    double w,
    double h,
    double p,
  ) {
    final theme = Theme.of(context);
    final peach = theme.scaffoldBackgroundColor;
    final white = theme.colorScheme.surface;
    final wide = w >= 760;
    final top = MediaQuery.of(context).padding.top;
    final bottomSafe = MediaQuery.of(context).padding.bottom;
    final offset = p * h; // how far the page has really scrolled, in pixels

    // ---- two screens, one above the other, that scroll together ----
    // Screen one is peach and fades into white along its bottom edge; screen two is white and starts exactly where that fade ends,
    // so scrolling reads as one continuous page. Both are moved by the same number of pixels as the scroll.
    final page1 = Positioned(
      left: 0,
      right: 0,
      top: -offset,
      height: h,
      child: Stack(
        children: [
          // The whole screen is one long, eased fade: flat peach for the top half, then a slow change to white over the
          // bottom 45%, so there is no visible edge anywhere. It sits UNDER the content so it never washes out the cards.
          Positioned.fill(
            child: DecoratedBox(
              key: const Key('page-one-background'),
              decoration: BoxDecoration(gradient: softFade(peach, white)),
            ),
          ),
          _PageOne(top: top, wide: wide),
        ],
      ),
    );

    final side = math.min(math.min(h * 0.30, w * 0.40), 260.0);
    // the lower two cards trail a little behind the page as it arrives, so they settle after the middle one
    Widget card(
      double fx,
      double fy,
      String key,
      String title,
      List<String> lines, {
      double lag = 0,
    }) {
      return Positioned(
        left: w * fx - side / 2,
        top: h * fy - side / 2 + (1 - p) * h * lag,
        width: side,
        height: side,
        child: _SquircleCard(
          key: Key(key),
          title: title,
          lines: lines,
          color: peach,
        ),
      );
    }

    final who = [for (final o in s.operators) '${o['name']} · ${o['via']}'];
    final page2 = Positioned(
      left: 0,
      right: 0,
      top: h - offset,
      height: h,
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          Positioned.fill(child: ColoredBox(color: white)),
          card(0.5, 0.407, 'card-something', 'ON HIS MIND', [
            s.lastThought ?? (s.online ? 'Nothing yet' : '—'),
          ]),
          card(
            0.234,
            0.708,
            'card-operators',
            "WHO'S ON",
            who.isEmpty
                ? [s.online ? 'Nobody else right now' : '—']
                : who.take(4).toList(),
            lag: 0.10,
          ),
          card(
            0.772,
            0.708,
            'card-tasks',
            'RECENT TASKS',
            s.online && s.recentTasks.isNotEmpty
                ? s.recentTasks.take(3).toList()
                : ['—'],
            lag: 0.10,
          ),
        ],
      ),
    );

    // ---- the icons: from the bottom row out to the edges, over the whole scroll ----
    final e = Curves.easeInOutCubic.transform(p);
    final startY = h - 66 - bottomSafe;
    const startSize = 38.0;
    final endSize = math.min(60.0, math.max(44.0, w * 0.055));
    final size = startSize + (endSize - startSize) * e;
    final icons = <Widget>[];
    for (var i = 0; i < widget.items.length; i++) {
      final from = Offset(w * (i + 0.5) / widget.items.length, startY);
      final to = Offset(w * _iconEnds[i].dx, h * _iconEnds[i].dy);
      final bow =
          math.sin(math.pi * e) *
          w *
          0.035 *
          (i < 2 ? -1 : 1); // a gentle curve, not a straight line
      final at = Offset.lerp(from, to, e)! + Offset(bow, 0);
      icons.add(
        Positioned(
          left: at.dx - size / 2 - 12,
          top: at.dy - size / 2 - 12,
          child: Tooltip(
            message: widget.items[i].label,
            child: Semantics(
              button: true,
              selected: widget.selected == i,
              label: widget.items[i].label,
              child: InkResponse(
                key: Key('nav-${widget.items[i].id}'),
                onTap: () => widget.onSelect(i),
                radius: size * 0.9,
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Icon(
                    widget.items[i].icon,
                    size: size,
                    color: widget.selected == i
                        ? theme.colorScheme.primary
                        : theme.colorScheme.onSurface,
                  ),
                ),
              ),
            ),
          ),
        ),
      );
    }

    return Stack(
      clipBehavior: Clip.hardEdge,
      children: [page1, page2, ...icons],
    );
  }
}

class _Scene extends SliverPersistentHeaderDelegate {
  _Scene({required this.height, required this.builder});
  final double height;
  final Widget Function(BuildContext) builder;

  @override
  double get minExtent => height;
  @override
  double get maxExtent => height;

  @override
  Widget build(
    BuildContext context,
    double shrinkOffset,
    bool overlapsContent,
  ) => SizedBox(height: height, child: builder(context));

  @override
  bool shouldRebuild(covariant _Scene old) => true; // it reads live app state, and is cheap
}

/// A rounded "squircle" card: a small caption and a few lines.
class _SquircleCard extends StatelessWidget {
  const _SquircleCard({
    super.key,
    required this.title,
    required this.lines,
    required this.color,
  });
  final String title;
  final List<String> lines;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final ink = Theme.of(context).colorScheme.onSurface;
    return LayoutBuilder(
      builder: (context, box) {
        final small = box.maxWidth < 200;
        return Material(
          color: color,
          shape: RoundedSuperellipseBorder(
            borderRadius: BorderRadius.circular(box.maxWidth * 0.3),
          ),
          child: Padding(
            padding: EdgeInsets.all(box.maxWidth * 0.11),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(
                  title,
                  style: TextStyle(
                    fontSize: small ? 10 : 12,
                    letterSpacing: 1.2,
                    color: ink.withValues(alpha: 0.55),
                  ),
                ),
                const SizedBox(height: 8),
                for (final line in lines.take(small ? 2 : 3))
                  Padding(
                    padding: const EdgeInsets.only(bottom: 4),
                    child: Text(
                      line,
                      textAlign: TextAlign.center,
                      maxLines: lines.length == 1 ? 5 : 2,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        fontSize: small ? 12 : 14,
                        height: 1.25,
                        color: ink,
                      ),
                    ),
                  ),
              ],
            ),
          ),
        );
      },
    );
  }
}

/// Page one: BOB, Online, the welcome and three info pills.
class _PageOne extends StatelessWidget {
  const _PageOne({required this.top, required this.wide});
  final double top;
  final bool wide;

  static String _money(Object? v) =>
      v is num ? '\$${v.toStringAsFixed(2)}' : '—';

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final st = s.status, usage = s.usage, vitals = s.vitals;
    final on = s.online && st.isNotEmpty;
    final mode = on ? s.mode : '—';
    final modeDetail = on
        ? 'AI ${st['thinking'] == true ? 'thinking' : 'idle'} · camera ${st['camera'] == 'OFF' ? 'off' : 'on'}'
        : "Can't reach ${s.robotName}";
    final cost = on ? _money(usage['today']) : '—';
    final costDetail = on
        ? '${_money(usage['all'])} all time · ${_money(st['cost'])} this run'
        : null;
    final temp = on && vitals['temp_c'] is num
        ? '${(vitals['temp_c'] as num).round()} °C'
        : '—';
    final room = on ? st['room'] : null;
    final piDetail = !on
        ? null
        : room != null
        ? 'in the $room'
        : [
            if (vitals['load'] is num)
              'load ${(vitals['load'] as num).toStringAsFixed(1)}',
            if (vitals['mem_mb'] != null) '${vitals['mem_mb']} MB free',
          ].join(' · ');
    final height = wide ? 160.0 : 112.0;
    final pills = [
      InfoPill(
        key: const Key('pill-mode'),
        label: 'RIGHT NOW',
        value: mode,
        detail: modeDetail,
        height: height,
        onTap: () => _open(context),
      ),
      InfoPill(
        key: const Key('pill-cost'),
        label: 'CLAUDE COST TODAY',
        value: cost,
        detail: costDetail,
        height: height,
        onTap: () => _open(context),
      ),
      InfoPill(
        key: const Key('pill-pi'),
        label: room != null ? 'WHERE HE IS' : 'THE PI',
        value: room != null ? '$room' : temp,
        detail: room != null ? temp : piDetail,
        height: height,
        onTap: () => _open(context),
      ),
    ];
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 1100),
        child: SingleChildScrollView(
          physics:
              const NeverScrollableScrollPhysics(), // the page scrolls as a whole; this only avoids an overflow on a tiny window
          padding: EdgeInsets.fromLTRB(
            wide ? 48 : 20,
            top + (wide ? 36 : 16),
            wide ? 48 : 20,
            190,
          ),
          child: Column(
            children: [
              BobHeader(
                online: s.online,
                problem: s.online ? null : s.problem ?? 'Offline',
              ),
              SizedBox(height: wide ? 56 : 28),
              Greeting(name: s.userName, size: wide ? 76 : 52),
              SizedBox(height: wide ? 64 : 32),
              if (wide)
                Row(
                  children: [
                    for (var i = 0; i < pills.length; i++) ...[
                      if (i > 0) const SizedBox(width: 28),
                      Expanded(child: pills[i]),
                    ],
                  ],
                )
              else
                for (final p in pills)
                  Padding(padding: const EdgeInsets.only(bottom: 12), child: p),
            ],
          ),
        ),
      ),
    );
  }

  void _open(BuildContext context) {
    context.findAncestorStateOfType<_HomePageState>()?.widget.onOpen?.call(1);
  }
}
