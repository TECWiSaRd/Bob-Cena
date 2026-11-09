import 'dart:convert';

import 'package:flutter/material.dart' show ThemeMode;
import 'package:shared_preferences/shared_preferences.dart';

/// One paired Bob: where he is, which certificate to trust, and this device's token.
class BobProfile {
  BobProfile({
    required this.name,
    required this.host,
    required this.port,
    required this.fingerprint,
    required this.token,
    required this.device,
    this.user,
  });

  final String name;
  final String host;
  final int port;
  final String
  fingerprint; // SHA-256 of Bob's HTTPS certificate: the app accepts only this one
  final String token;
  final String device; // the name this device was paired under
  final String? user; // who is using the app, for "Welcome back, Adam"

  BobProfile copyWith({String? host, int? port, String? user}) => BobProfile(
    name: name,
    host: host ?? this.host,
    port: port ?? this.port,
    fingerprint: fingerprint,
    token: token,
    device: device,
    user: user ?? this.user,
  );

  Map<String, dynamic> toJson() => {
    'name': name,
    'host': host,
    'port': port,
    'fingerprint': fingerprint,
    'token': token,
    'device': device,
    if (user != null) 'user': user,
  };

  static BobProfile? fromJson(Object? data) {
    if (data is! Map) return null;
    try {
      return BobProfile(
        name: data['name'] as String,
        host: data['host'] as String,
        port: data['port'] as int,
        fingerprint: data['fingerprint'] as String,
        token: data['token'] as String,
        device: data['device'] as String,
        user: data['user'] as String?,
      );
    } catch (_) {
      return null;
    }
  }
}

class ProfileStore {
  static const _oldKey = 'bob_profile_v1'; // 26.11 and before: one Bob
  static const _listKey = 'bob_profiles_v2'; // every paired Bob
  static const _activeKey = 'bob_active_v2'; // fingerprint of the Bob in use

  /// All paired Bobs. A Bob is told apart by his certificate's fingerprint, so pairing the same Bob again replaces him.
  /// A single Bob saved by an older version is picked up here.
  Future<List<BobProfile>> loadAll() async {
    final prefs = await SharedPreferences.getInstance();
    final out = <BobProfile>[];
    final raw = prefs.getString(_listKey);
    if (raw != null) {
      try {
        final data = jsonDecode(raw);
        if (data is List) {
          for (final item in data) {
            final p = BobProfile.fromJson(item);
            if (p != null && !out.any((o) => o.fingerprint == p.fingerprint)) {
              out.add(p);
            }
          }
        }
      } catch (_) {}
      return out;
    }
    final old = prefs.getString(_oldKey);
    if (old != null) {
      try {
        final p = BobProfile.fromJson(jsonDecode(old));
        if (p != null) out.add(p);
      } catch (_) {}
    }
    return out;
  }

  Future<String?> loadActive() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_activeKey);
  }

  Future<void> saveAll(List<BobProfile> profiles, String? active) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(
      _listKey,
      jsonEncode([for (final p in profiles) p.toJson()]),
    );
    if (active == null) {
      await prefs.remove(_activeKey);
    } else {
      await prefs.setString(_activeKey, active);
    }
    await prefs.remove(_oldKey); // the list is now the one place they live
  }

  static const _themeKey = 'bob_theme_mode_v1';

  /// Light, dark, or follow the device (the default).
  Future<ThemeMode> loadThemeMode() async {
    final prefs = await SharedPreferences.getInstance();
    return switch (prefs.getString(_themeKey)) {
      'light' => ThemeMode.light,
      'dark' => ThemeMode.dark,
      _ => ThemeMode.system,
    };
  }

  Future<void> saveThemeMode(ThemeMode mode) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_themeKey, mode.name);
  }
}
