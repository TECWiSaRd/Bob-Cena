import 'dart:convert';

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
  });

  final String name;
  final String host;
  final int port;
  final String fingerprint; // SHA-256 of Bob's HTTPS certificate: the app accepts only this one
  final String token;
  final String device; // the name this device was paired under

  BobProfile copyWith({String? host, int? port}) => BobProfile(
        name: name,
        host: host ?? this.host,
        port: port ?? this.port,
        fingerprint: fingerprint,
        token: token,
        device: device,
      );

  Map<String, dynamic> toJson() => {
        'name': name,
        'host': host,
        'port': port,
        'fingerprint': fingerprint,
        'token': token,
        'device': device,
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
      );
    } catch (_) {
      return null;
    }
  }
}

class ProfileStore {
  static const _key = 'bob_profile_v1';

  Future<BobProfile?> load() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_key);
    if (raw == null) return null;
    try {
      return BobProfile.fromJson(jsonDecode(raw));
    } catch (_) {
      return null;
    }
  }

  Future<void> save(BobProfile profile) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_key, jsonEncode(profile.toJson()));
  }

  Future<void> clear() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_key);
  }
}
