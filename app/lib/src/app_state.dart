import 'dart:async';

import 'package:flutter/foundation.dart';

import 'client.dart';
import 'discovery.dart';
import 'profile.dart';

/// Everything the screens show: who we are paired with, Bob's latest status, and whether he is reachable.
class AppState extends ChangeNotifier {
  AppState({ProfileStore? store, this.pollEvery = const Duration(seconds: 1)}) : _store = store ?? ProfileStore();

  final ProfileStore _store;
  final Duration pollEvery;

  bool loading = true;
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

  Future<void> load() async {
    profile = await _store.load();
    loading = false;
    if (profile != null) _connect(profile!);
    notifyListeners();
  }

  void _connect(BobProfile p) {
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
    try {
      await client?.unpair();
    } catch (_) {}
    _timer?.cancel();
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
    if (c == null || _polling) return;
    _polling = true;
    try {
      final s = await c.status();
      status = s;
      online = true;
      problem = null;
      _failures = 0;
    } on BobApiException catch (e) {
      online = false;
      if (e.unauthorized) {
        revoked = true;
        problem = 'Bob no longer recognises this device. Pair it again.';
        _timer?.cancel();
      } else {
        problem = e.message;
        _failures++;
      }
    } catch (e) {
      online = false;
      _failures++;
      problem = c.certificateRejected
          ? "The certificate doesn't match the one this device was paired with. This may not be your Bob."
          : "Can't reach ${profile?.name ?? 'Bob'}";
    } finally {
      _polling = false;
    }
    if (_failures >= 4) unawaited(_maybeRediscover());
    notifyListeners();
  }

  /// Bob's address can change (the router hands out a new one). Look for him on the network and, if the certificate
  /// matches the one we are paired with, follow him there.
  Future<void> _maybeRediscover() async {
    final p = profile;
    if (p == null || DateTime.now().difference(_lastRediscovery) < const Duration(seconds: 30)) return;
    _lastRediscovery = DateTime.now();
    final d = BobDiscovery();
    await d.start();
    await Future<void>.delayed(const Duration(seconds: 4));
    final match = d.current.where((b) => b.fingerprintPrefix != null && p.fingerprint.startsWith(b.fingerprintPrefix!));
    await d.stop();
    if (match.isNotEmpty && (match.first.host != p.host || match.first.port != p.port)) {
      await setProfile(p.copyWith(host: match.first.host, port: match.first.port));
    }
  }

  Future<String> send(String text) async {
    final c = client;
    if (c == null) return '';
    final out = await c.command(text);
    unawaited(poll());
    return out;
  }

  Future<void> drive(double left, double right) async {
    try {
      await client?.drive(left, right);
    } catch (_) {}
  }

  // ---- handy views of the status ----
  String get robotName => profile?.name ?? 'Bob';
  String get mode => (status['mode'] ?? '...').toString();
  bool get estop => mode == 'E-STOP';
  List<String> get rooms => ((status['rooms'] as List?) ?? const []).map((e) => e.toString()).toList();
  bool get hasMusic => status['music_enabled'] == true;

  @override
  void dispose() {
    _timer?.cancel();
    client?.close();
    super.dispose();
  }
}
