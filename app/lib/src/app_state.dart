import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart' show ThemeMode;

import 'client.dart';
import 'discovery.dart';
import 'profile.dart';

/// Everything the screens show: who we are paired with, Bob's latest status, and whether he is reachable.
class AppState extends ChangeNotifier {
  AppState({
    ProfileStore? store,
    this.pollEvery = const Duration(seconds: 1),
    this.autoConnect = true,
  }) : _store = store ?? ProfileStore();

  final ProfileStore _store;
  final Duration pollEvery;
  final bool autoConnect; // false in tests that must not touch the network

  bool loading = true;
  ThemeMode themeMode =
      ThemeMode.system; // the appearance setting (More, Appearance)
  BobProfile? profile;
  BobClient? client;
  Map<String, dynamic> status = {};
  bool online = false;
  String? problem;
  bool revoked = false; // Bob no longer recognises this device
  Timer? _timer;
  int _failures = 0;
  DateTime _lastRediscovery = DateTime.fromMillisecondsSinceEpoch(0);
  bool _polling = false;
  int _session = 0;

  Future<void> load() async {
    profile = await _store.load();
    themeMode = await _store.loadThemeMode();
    loading = false;
    if (profile != null) _connect(profile!);
    notifyListeners();
  }

  void _connect(BobProfile p) {
    _session++;
    if (!autoConnect) {
      return;
    }
    client?.close();
    client = BobClient.fromProfile(p);
    revoked = false;
    problem = null;
    _failures = 0;
    _timer?.cancel();
    _timer = Timer.periodic(pollEvery, (_) => poll());
    poll();
  }

  Future<void> setProfile(BobProfile p) async {
    await _store.save(p);
    profile = p;
    status = {};
    _connect(p);
    notifyListeners();
  }

  /// Forget Bob on this device. Also tells Bob to forget the device if he can be reached.
  Future<void> forget() async {
    // In-flight polls belong to the old identity and must not repopulate the
    // UI while this device is being unpaired.
    _session++;
    _timer?.cancel();
    _timer = null;
    try {
      await client?.unpair();
    } catch (_) {}
    client?.close();
    client = null;
    profile = null;
    status = {};
    online = false;
    revoked = false;
    problem = null;
    await _store.clear();
    notifyListeners();
  }

  Future<void> poll() async {
    final c = client;
    if (c == null || _polling || revoked) return;
    final session = _session;
    _polling = true;
    var stale = false;
    try {
      final s = await c.status();
      stale = session != _session || !identical(c, client);
      if (!stale) {
        status = s;
        online = true;
        problem = null;
        _failures = 0;
      }
    } on BobApiException catch (e) {
      stale = session != _session || !identical(c, client);
      if (!stale) {
        online = false;
        if (e.unauthorized) {
          revoked = true;
          problem = 'Bob no longer recognises this device. Pair it again.';
          _timer?.cancel();
          _timer = null;
        } else {
          problem = e.message;
          _failures++;
        }
      }
    } catch (e) {
      stale = session != _session || !identical(c, client);
      if (!stale) {
        online = false;
        _failures++;
        problem = c.certificateRejected
            ? "The certificate doesn't match the one this device was paired with. This may not be your Bob, or Bob made a new certificate. If it is your Bob, forget him here and pair again."
            : "Can't reach ${profile?.name ?? 'Bob'}";
      }
    } finally {
      _polling = false;
    }
    if (stale) {
      // The identity changed while this request ran. Show the new state; if the
      // new connection's first poll was skipped by the one-flight guard, run it
      // now. Only a real switch needs this, not every stale finish.
      notifyListeners();
      if (session != _session && client != null) unawaited(poll());
      return;
    }
    if (_failures >= 4) unawaited(_maybeRediscover());
    notifyListeners();
  }

  /// Bob's address can change (the router hands out a new one). Look for him on the network and, if the certificate
  /// matches the one we are paired with, follow him there.
  Future<void> _maybeRediscover() async {
    final p = profile;
    final session = _session;
    if (p == null ||
        DateTime.now().difference(_lastRediscovery) <
            const Duration(seconds: 30)) {
      return;
    }
    _lastRediscovery = DateTime.now();
    final d = BobDiscovery();
    Iterable<FoundBob> match = const [];
    try {
      await d.start();
      await Future<void>.delayed(const Duration(seconds: 4));
      match = d.current
          .where(
            (b) =>
                b.fingerprintPrefix != null &&
                p.fingerprint.startsWith(b.fingerprintPrefix!),
          )
          .toList();
    } catch (_) {
      // No multicast permission, a socket that will not bind...: just try again later.
    } finally {
      try {
        await d.stop();
      } catch (_) {}
    }
    // The user may have unpaired or selected another Bob while discovery was
    // listening. Never resurrect or overwrite that newer choice.
    if (session != _session || !identical(profile, p)) return;
    if (match.isNotEmpty &&
        (match.first.host != p.host || match.first.port != p.port)) {
      await setProfile(
        p.copyWith(host: match.first.host, port: match.first.port),
      );
    }
  }

  Future<String> send(String text) async {
    final c = client;
    if (c == null) return '';
    final out = await c.command(text);
    unawaited(poll());
    return out;
  }

  /// Flip one setting. The screen changes at once (so the switch feels instant); if Bob can't be told, it flips back.
  /// [patch] is what the status looks like once it has worked, e.g. {'sleep': true}.
  Future<String> toggle(Map<String, dynamic> patch, String command) async {
    final before = {for (final k in patch.keys) k: status[k]};
    status = {...status, ...patch};
    notifyListeners();
    try {
      return await send(command);
    } catch (_) {
      status = {...status, ...before};
      notifyListeners();
      rethrow;
    }
  }

  Future<void> drive(double left, double right) async {
    try {
      await client?.drive(left, right);
    } catch (_) {}
  }

  /// Who is using the app: what they typed, else a guess from the device name ("Adam's Mac"), else nobody.
  String? get userName {
    final typed = profile?.user?.trim();
    if (typed != null && typed.isNotEmpty) return typed;
    final m = RegExp(r"^(.+?)['\u2019]s\b").firstMatch(profile?.device ?? '');
    final guess = m?.group(1)?.trim();
    return (guess == null || guess.isEmpty) ? null : guess;
  }

  Future<void> setThemeMode(ThemeMode mode) async {
    themeMode = mode;
    notifyListeners();
    await _store.saveThemeMode(mode);
  }

  Future<void> setUserName(String name) async {
    final p = profile;
    if (p == null) return;
    final updated = p.copyWith(user: name.trim());
    await _store.save(updated);
    profile = updated;
    notifyListeners();
  }

  // ---- handy views of the status ----
  String get robotName => profile?.name ?? 'Bob';
  String get mode => (status['mode'] ?? '...').toString();
  bool get estop => mode == 'E-STOP';
  Map<String, dynamic> get usage =>
      ((status['usage'] as Map?) ?? const {}).cast<String, dynamic>();
  Map<String, dynamic> get vitals =>
      ((status['vitals'] as Map?) ?? const {}).cast<String, dynamic>();
  List<String> get rooms => ((status['rooms'] as List?) ?? const [])
      .map((e) => e.toString())
      .toList();
  bool get hasMusic => status['music_enabled'] == true;

  /// Who is using Bob right now: [{name, via}].
  List<Map<String, dynamic>> get operators =>
      ((status['operators'] as List?) ?? const [])
          .whereType<Map>()
          .map((e) => e.cast<String, dynamic>())
          .toList();

  List<Map<String, dynamic>> get _logLines =>
      ((status['log'] as List?) ?? const [])
          .whereType<Map>()
          .map((e) => e.cast<String, dynamic>())
          .toList();

  /// The last thing Bob said or thought, from the log.
  String? get lastThought {
    for (final row in _logLines.reversed) {
      if (row['t'] == 'BOB' || row['t'] == 'SAY') {
        return row['m'].toString();
      }
    }
    return null;
  }

  /// A few recent things he did or was told: the event timeline if it is on, else the log.
  List<String> get recentTasks {
    final events = ((status['events'] as List?) ?? const [])
        .whereType<Map>()
        .toList();
    if (events.isNotEmpty) {
      return [
        for (final e in events.reversed.take(4))
          '${eventClock(e['t'])} ${e['kind']} ${e['text'] ?? ''}'.trim(),
      ];
    }
    const kinds = {'MOVE', 'BOB', 'SAY', 'HEARD', 'RADIO', 'YOU'};
    return [
      for (final row
          in _logLines.reversed.where((r) => kinds.contains(r['t'])).take(4))
        row['m'].toString(),
    ];
  }

  bool get aiOn => status['auto'] == true;
  bool get following => status['follow'] == true;
  bool get sleeping => status['sleep'] == true;
  bool get soundOn => status['muted'] != true;
  bool get cameraOn =>
      (status['camera'] ?? 'on').toString().toLowerCase() == 'on';
  bool get going => status['going'] == true;

  @override
  void dispose() {
    _timer?.cancel();
    client?.close();
    super.dispose();
  }
}

/// The clock part of an event timestamp such as "2026-10-25 14:03:09": HH:MM, or HH:MM:SS with [seconds].
/// Anything that is not a date followed by a time is returned unchanged.
String eventClock(Object? raw, {bool seconds = false}) {
  final value = (raw ?? '').toString();
  final m = RegExp(
    r'^\d{4}-\d{2}-\d{2}[ T](\d{2}:\d{2})(:\d{2})?',
  ).firstMatch(value);
  if (m == null) return value;
  return seconds && m.group(2) != null
      ? '${m.group(1)}${m.group(2)}'
      : m.group(1)!;
}
