import 'dart:async';

import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart' show ThemeMode;

import 'app_update.dart';
import 'client.dart';
import 'discovery.dart';
import 'installer.dart';
import 'profile.dart';

/// Everything the screens show: who we are paired with, Bob's latest status, and whether he is reachable.
class AppState extends ChangeNotifier {
  AppState({
    ProfileStore? store,
    this.pollEvery = const Duration(seconds: 1),
    this.autoConnect = true,
    this.checkUpdatesAtStart = false,
    Future<ReleaseInfo?> Function()? fetchRelease,
    Future<bool> Function(Uri)? openUrl,
    AppInstaller? installer,
    bool selfInstall =
        true, // false: this device only opens the browser (tests)
    Directory? downloadDir,
    Future<void> Function(Uri, File, String?, void Function(double))? download,
  }) : _store = store ?? ProfileStore(),
       _fetchRelease = fetchRelease ?? fetchLatestRelease,
       _openUrl = openUrl ?? openInBrowser,
       _installer = selfInstall
           ? (installer ?? installerForThisDevice())
           : null,
       _downloadDir = downloadDir,
       _download = download;

  final ProfileStore _store;
  final Duration pollEvery;
  final bool autoConnect; // false in tests that must not touch the network
  final bool
  checkUpdatesAtStart; // the real app asks GitHub once at start-up; tests don't
  bool _disposed = false;
  final Future<ReleaseInfo?> Function() _fetchRelease;
  final Future<bool> Function(Uri) _openUrl;
  final AppInstaller?
  _installer; // null on devices that can't install themselves
  final Directory? _downloadDir;
  final Future<void> Function(Uri, File, String?, void Function(double))?
  _download;

  /// Where the in-app update is: idle, downloading (with [updateProgress]) or installing.
  String updateStage = 'idle';
  double updateProgress = 0;
  bool get canInstallHere => _installer != null;

  /// The newest GitHub release, once asked (More, App updates).
  ReleaseInfo? latestRelease;
  bool checkingUpdate = false;
  String? updateProblem;
  bool get updateAvailable =>
      latestRelease != null && isNewer(latestRelease!.version, appVersion);

  bool loading = true;
  ThemeMode themeMode =
      ThemeMode.system; // the appearance setting (More, Appearance)
  BobProfile? profile; // the Bob in use right now
  List<BobProfile> profiles = []; // every Bob paired on this device
  bool addingBob = false; // showing the pairing screen to add one more
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
    profiles = await _store.loadAll();
    final active = await _store.loadActive();
    profile = profiles.isEmpty
        ? null
        : profiles.firstWhere(
            (p) => p.fingerprint == active,
            orElse: () => profiles.first,
          );
    themeMode = await _store.loadThemeMode();
    loading = false;
    if (profile != null) _connect(profile!);
    notifyListeners();
    if (checkUpdatesAtStart) unawaited(checkForUpdate(quiet: true));
  }

  /// Asks GitHub for the newest release. [quiet] (the check at start-up) says nothing when it can't reach GitHub.
  Future<void> checkForUpdate({bool quiet = false}) async {
    if (checkingUpdate) return;
    checkingUpdate = true;
    if (!quiet) updateProblem = null;
    notifyListeners();
    try {
      final r = await _fetchRelease();
      if (r == null) {
        if (!quiet) {
          updateProblem = "GitHub's answer wasn't a release I understand.";
        }
      } else {
        latestRelease = r;
      }
    } catch (_) {
      if (!quiet) updateProblem = "Can't reach GitHub just now.";
    } finally {
      checkingUpdate = false;
      if (!_disposed) notifyListeners();
    }
  }

  /// Starts the download of the newest release in the browser (or its page when it has no file for this device).
  Future<bool> downloadUpdate() async {
    final r = latestRelease;
    if (r == null) return false;
    try {
      return await _openUrl(r.download ?? r.page);
    } catch (_) {
      return false;
    }
  }

  /// Downloads the newest release inside the app and installs it. Returns null when it worked (on the Mac the app
  /// closes and reopens by itself), else what went wrong in plain words. Without a file or an installer for this
  /// device it falls back to the browser.
  Future<String?> installUpdate() async {
    final r = latestRelease;
    final inst = _installer;
    if (r == null) return 'Check for updates first.';
    if (updateStage != 'idle') return null;
    if (inst == null || r.download == null) {
      return await downloadUpdate()
          ? null
          : "Couldn't open the browser. The release is on GitHub: ${r.page}";
    }
    final dir = _downloadDir ?? Directory.systemTemp;
    final name = r.download!.pathSegments.isEmpty
        ? 'bob-update'
        : r.download!.pathSegments.last;
    final file = File('${dir.path}/$name');
    updateStage = 'downloading';
    updateProgress = 0;
    notifyListeners();
    try {
      final dl =
          _download ??
          (u, f, sum, tick) =>
              downloadFile(u, f, sha256Hex: sum, onProgress: tick);
      await dl(r.download!, file, r.sha256, (v) {
        updateProgress = v;
        if (!_disposed) notifyListeners();
      });
      updateStage = 'installing';
      notifyListeners();
      await inst.install(file);
      return null;
    } on UpdateException catch (e) {
      return e.message;
    } catch (e) {
      return "The update didn't work: $e";
    } finally {
      updateStage = 'idle';
      if (!_disposed) notifyListeners();
    }
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

  Future<void> _saveProfiles() =>
      _store.saveAll(profiles, profile?.fingerprint);

  /// Adds a Bob (or replaces the same Bob, told apart by his certificate) and starts using him.
  Future<void> setProfile(BobProfile p) async {
    final i = profiles.indexWhere((o) => o.fingerprint == p.fingerprint);
    profiles = [...profiles];
    if (i >= 0) {
      profiles[i] = p;
    } else {
      profiles.add(p);
    }
    profile = p;
    addingBob = false;
    await _saveProfiles();
    status = {};
    _connect(p);
    notifyListeners();
  }

  /// Use another of the paired Bobs.
  Future<void> switchTo(String fingerprint) async {
    if (profile?.fingerprint == fingerprint) return;
    final p = profiles.where((o) => o.fingerprint == fingerprint).firstOrNull;
    if (p == null) return;
    // In-flight polls and drive commands belong to the Bob we are leaving.
    unawaited(client?.drive(0, 0).catchError((_) {}));
    profile = p;
    status = {};
    online = false;
    await _saveProfiles();
    _connect(p);
    notifyListeners();
  }

  /// Show the pairing screen so another Bob can be added; the Bob in use stays connected underneath.
  void startAddingBob() {
    addingBob = true;
    notifyListeners();
  }

  void cancelAddingBob() {
    addingBob = false;
    notifyListeners();
  }

  /// Forget the Bob in use on this device. Also tells him to forget the device if he can be reached.
  /// If other Bobs are paired, the next one is used; otherwise the pairing screen shows.
  Future<void> forget() async {
    // In-flight polls belong to the old identity and must not repopulate the
    // UI while this device is being unpaired.
    _session++;
    _timer?.cancel();
    _timer = null;
    final old = profile;
    try {
      await client?.unpair();
    } catch (_) {}
    client?.close();
    client = null;
    profiles = [
      for (final p in profiles)
        if (p.fingerprint != old?.fingerprint) p,
    ];
    profile = profiles.isEmpty ? null : profiles.first;
    status = {};
    online = false;
    revoked = false;
    problem = null;
    addingBob = false;
    await _saveProfiles();
    if (profile != null) _connect(profile!);
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
    profile = updated;
    profiles = [
      for (final o in profiles)
        o.fingerprint == updated.fingerprint ? updated : o,
    ];
    await _saveProfiles();
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
    _disposed = true;
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
