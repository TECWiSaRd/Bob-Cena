import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'app_state.dart';
import 'design.dart';
import 'home_page.dart';
import 'tabs.dart';
import 'theme.dart';

const _items = [
  NavItem('drive', 'Drive', Icons.sports_esports),
  NavItem('status', 'Status', Icons.speed),
  NavItem('chat', 'Chat', Icons.chat_bubble_outline),
  NavItem('more', 'More', Icons.tune),
];

/// The main screen once paired: the home page, four sections reached by the bar at the bottom, and an emergency stop that is
/// always on screen.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int? _tab; // null = the home page
  final _homeProgress = ValueNotifier<double>(
    0,
  ); // how far the home page has scrolled, 0 to 1

  @override
  void dispose() {
    _homeProgress.dispose();
    super.dispose();
  }

  Future<void> _estop(AppState s) async {
    unawaited(s.drive(0, 0));
    try {
      await s.send('/estop');
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text("Couldn't reach Bob to stop him!")),
        );
      }
    }
  }

  void _select(int i) => setState(
    () => _tab = _tab == i ? null : i,
  ); // tapping the open section again goes home

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final scheme = Theme.of(context).colorScheme;
    final top = MediaQuery.of(context).padding.top;

    final banners = Column(
      children: [
        if (_tab != null && (!s.online || s.problem != null))
          MaterialBanner(
            backgroundColor: scheme.surface,
            content: Text(s.problem ?? 'Connecting...'),
            leading: Icon(s.revoked ? Icons.lock : Icons.cloud_off),
            actions: [
              if (s.revoked)
                TextButton(onPressed: s.forget, child: const Text('Pair again'))
              else
                TextButton(onPressed: s.poll, child: const Text('Retry')),
            ],
          ),
        if (_tab == null && s.revoked)
          MaterialBanner(
            backgroundColor: scheme.surface,
            content: Text(s.problem ?? ''),
            leading: const Icon(Icons.lock),
            actions: [
              TextButton(onPressed: s.forget, child: const Text('Pair again')),
            ],
          ),
        if (s.estop)
          MaterialBanner(
            backgroundColor: scheme.errorContainer,
            content: const Text('Emergency stop is ON. The motors are locked.'),
            actions: [
              TextButton(
                onPressed: () => s.send('/clear'),
                child: const Text('Release'),
              ),
            ],
          ),
      ],
    );

    final body = _tab == null
        ? HomePage(
            items: _items,
            selected: null,
            onSelect: _select,
            progress: _homeProgress,
            onOpen: (i) => setState(() => _tab = i),
          )
        : Column(
            children: [
              Padding(
                padding: EdgeInsets.fromLTRB(24, top + 12, 24, 4),
                child: Align(
                  alignment: Alignment.centerLeft,
                  child: BobHeader(
                    online: s.online,
                    problem: s.problem,
                    compact: true,
                    onTitleTap: () => setState(() => _tab = null),
                  ),
                ),
              ),
              Expanded(
                child: IndexedStack(
                  index: _tab!,
                  children: const [
                    DriveTab(),
                    StatusTab(),
                    ChatTab(),
                    MoreTab(),
                  ],
                ),
              ),
            ],
          );

    return Scaffold(
      body: Stack(
        children: [
          Positioned.fill(
            child: Column(
              children: [
                banners,
                Expanded(child: body),
              ],
            ),
          ),
          Align(
            alignment: Alignment.bottomCenter,
            // On the home page there is no bar under the stop button; it rides above where the icons are, and settles
            // lower once the icons have flowed away to the edges.
            child: ValueListenableBuilder<double>(
              valueListenable: _homeProgress,
              builder: (context, p, child) {
                final lift = _tab == null
                    ? (104 + MediaQuery.of(context).padding.bottom) * (1 - p) +
                          20 * p
                    : 0.0;
                return Padding(
                  padding: EdgeInsets.only(bottom: lift),
                  child: child,
                );
              },
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  FilledButton.icon(
                    key: const Key('estop'),
                    onPressed: () => _estop(s),
                    style: FilledButton.styleFrom(
                      backgroundColor: BobColors.red,
                      foregroundColor: Colors.white,
                      elevation: 3,
                      shadowColor: Colors.black26,
                    ),
                    icon: const Icon(Icons.front_hand),
                    label: const Text(
                      'EMERGENCY STOP',
                      style: TextStyle(
                        fontWeight: FontWeight.w800,
                        letterSpacing: 0.5,
                      ),
                    ),
                  ),
                  if (_tab != null)
                    BobNavBar(items: _items, selected: _tab, onSelect: _select),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
