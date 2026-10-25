import 'package:flutter/material.dart';

/// The look of the app: warm peach, big white rounded cards, black ink, and a few chunky or handwritten touches.
class BobColors {
  static const peach = Color(0xFFFFE6CB);
  static const ink = Color(0xFF14110F);
  static const green = Color(0xFF7CB342);
  static const blue = Color(0xFF2330D6);
  static const red = Color(0xFFD62F2F);
  static const darkBackground = Color(0xFF1E1712);
  static const darkSurface = Color(0xFF2C231C);
}

/// Fonts bundled in assets/fonts (Open Font License).
class BobFonts {
  static const title = 'BobTitle'; // the BOB wordmark
  static const script = 'BobScript'; // "Welcome back,"
  static const heavy = 'Rubik'; // names and big numbers (use weight 800-900)
}

ThemeData bobTheme(Brightness brightness) {
  final dark = brightness == Brightness.dark;
  final bg = dark ? BobColors.darkBackground : BobColors.peach;
  final surface = dark ? BobColors.darkSurface : Colors.white;
  final ink = dark ? const Color(0xFFF6EDE4) : BobColors.ink;
  final scheme =
      ColorScheme.fromSeed(
        seedColor: BobColors.blue,
        brightness: brightness,
      ).copyWith(
        primary: dark ? const Color(0xFF9CA6FF) : BobColors.blue,
        surface: surface,
        onSurface: ink,
        surfaceContainerHighest: dark
            ? const Color(0xFF3A2F26)
            : const Color(0xFFF4EBE2),
        error: BobColors.red,
      );
  return ThemeData(
    useMaterial3: true,
    brightness: brightness,
    colorScheme: scheme,
    scaffoldBackgroundColor: bg,
    canvasColor: bg,
    cardTheme: CardThemeData(
      color: surface,
      elevation: 0,
      margin: const EdgeInsets.symmetric(vertical: 6),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(32)),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        shape: const StadiumBorder(),
        padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 14),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        shape: const StadiumBorder(),
        side: BorderSide(color: ink.withValues(alpha: 0.4)),
        padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 14),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(shape: const StadiumBorder()),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: surface,
      // a filled "underline" field with no line: the small label floats INSIDE the rounded shape instead of cutting its edge
      border: UnderlineInputBorder(
        borderRadius: BorderRadius.circular(28),
        borderSide: BorderSide.none,
      ),
      enabledBorder: UnderlineInputBorder(
        borderRadius: BorderRadius.circular(28),
        borderSide: BorderSide.none,
      ),
      focusedBorder: UnderlineInputBorder(
        borderRadius: BorderRadius.circular(28),
        borderSide: BorderSide(color: scheme.primary, width: 2),
      ),
      contentPadding: const EdgeInsets.symmetric(horizontal: 22, vertical: 16),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: surface,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(32)),
    ),
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      shape: const StadiumBorder(),
      backgroundColor: dark ? const Color(0xFF3A2F26) : BobColors.ink,
      contentTextStyle: const TextStyle(color: Colors.white),
    ),
    chipTheme: ChipThemeData(
      shape: const StadiumBorder(),
      side: BorderSide(color: ink.withValues(alpha: 0.15)),
    ),
    listTileTheme: ListTileThemeData(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
    ),
    dividerColor: ink.withValues(alpha: 0.1),
  );
}
