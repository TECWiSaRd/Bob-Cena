import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'app_state.dart';
import 'tabs.dart';

/// The main screen once paired: four tabs and an emergency stop that is always on screen.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _tab = 0;

  Future<void> _estop(AppState s) async {
    unawaited(s.drive(0, 0));
    try {
      await s.send('/estop');
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Couldn't reach Bob to stop him!")));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final scheme = Theme.of(context).colorScheme;
    final mode = s.mode;
    final modeColor = mode == 'E-STOP'
        ? scheme.error
        : mode == 'AUTO'
            ? Colors.green
            : mode == 'SLEEPING'
                ? Colors.indigo
                : scheme.tertiary;
    return Scaffold(
      appBar: AppBar(
        title: Row(children: [
          Icon(Icons.circle, size: 10, color: s.online ? Colors.green : scheme.error),
          const SizedBox(width: 8),
          Text(s.robotName),
          const SizedBox(width: 12),
          if (s.online) Chip(label: Text(mode), backgroundColor: modeColor.withValues(alpha: 0.2), visualDensity: VisualDensity.compact),
        ]),
      ),
      body: SafeArea(
        child: Column(children: [
          if (!s.online || s.problem != null)
            MaterialBanner(
              content: Text(s.problem ?? 'Connecting...'),
              leading: Icon(s.revoked ? Icons.lock : Icons.cloud_off),
              actions: [
                if (s.revoked) TextButton(onPressed: s.forget, child: const Text('Pair again')) else TextButton(onPressed: s.poll, child: const Text('Retry')),
              ],
            ),
          if (s.estop)
            MaterialBanner(
              backgroundColor: scheme.errorContainer,
              content: const Text('Emergency stop is ON. The motors are locked.'),
              actions: [TextButton(onPressed: () => s.send('/clear'), child: const Text('Release'))],
            ),
          Expanded(
            child: IndexedStack(index: _tab, children: const [DriveTab(), StatusTab(), ChatTab(), MoreTab()]),
          ),
        ]),
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _estop(s),
        backgroundColor: scheme.error,
        foregroundColor: scheme.onError,
        icon: const Icon(Icons.front_hand),
        label: const Text('EMERGENCY STOP', style: TextStyle(fontWeight: FontWeight.bold)),
      ),
      floatingActionButtonLocation: FloatingActionButtonLocation.centerFloat,
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.videogame_asset_outlined), selectedIcon: Icon(Icons.videogame_asset), label: 'Drive'),
          NavigationDestination(icon: Icon(Icons.monitor_heart_outlined), selectedIcon: Icon(Icons.monitor_heart), label: 'Status'),
          NavigationDestination(icon: Icon(Icons.chat_bubble_outline), selectedIcon: Icon(Icons.chat_bubble), label: 'Chat'),
          NavigationDestination(icon: Icon(Icons.tune), selectedIcon: Icon(Icons.tune), label: 'More'),
        ],
      ),
    );
  }
}
