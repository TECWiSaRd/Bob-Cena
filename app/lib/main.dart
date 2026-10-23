import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'src/app_state.dart';
import 'src/home_screen.dart';
import 'src/pair_screen.dart';

void main() {
  runApp(ChangeNotifierProvider(create: (_) => AppState()..load(), child: const BobApp()));
}

class BobApp extends StatelessWidget {
  const BobApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Bob',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF3B82F6)), useMaterial3: true),
      darkTheme: ThemeData(
          colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF3B82F6), brightness: Brightness.dark), useMaterial3: true),
      themeMode: ThemeMode.system,
      home: Consumer<AppState>(builder: (context, s, _) {
        if (s.loading) return const Scaffold(body: Center(child: CircularProgressIndicator()));
        return s.profile == null ? const PairScreen() : const HomeScreen();
      }),
    );
  }
}
