import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'src/app_state.dart';
import 'src/home_screen.dart';
import 'src/pair_screen.dart';
import 'src/theme.dart';

void main() {
  runApp(
    ChangeNotifierProvider(
      create: (_) => AppState(checkUpdatesAtStart: true)..load(),
      child: const BobApp(),
    ),
  );
}

class BobApp extends StatelessWidget {
  const BobApp({super.key});

  @override
  Widget build(BuildContext context) {
    // only the appearance setting is watched here, so the whole app isn't rebuilt every time Bob's status updates
    final mode = context.select<AppState, ThemeMode>((s) => s.themeMode);
    return MaterialApp(
      title: 'Bob',
      debugShowCheckedModeBanner: false,
      theme: bobTheme(Brightness.light),
      darkTheme: bobTheme(Brightness.dark),
      themeMode: mode,
      home: Consumer<AppState>(
        builder: (context, s, _) {
          if (s.loading) {
            return const Scaffold(
              body: Center(child: CircularProgressIndicator()),
            );
          }
          return s.profile == null ? const PairScreen() : const HomeScreen();
        },
      ),
    );
  }
}
