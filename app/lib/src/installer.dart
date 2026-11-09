import 'dart:async';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter/services.dart';

/// Downloads a release file and installs it without the browser.
/// Android hands the APK to the system installer (which always asks you to confirm, that is Android's rule);
/// the Mac unpacks the zip, swaps the new Bob.app in for the running one and opens it again.

class _OneDigest implements Sink<Digest> {
  late Digest value;
  @override
  void add(Digest data) => value = data;
  @override
  void close() {}
}

class UpdateException implements Exception {
  UpdateException(this.message);
  final String message;
  @override
  String toString() => message;
}

/// Saves [url] to [dest], reporting 0..1 as it goes. Only https. When [sha256Hex] is known the file must match it.
Future<void> downloadFile(
  Uri url,
  File dest, {
  String? sha256Hex,
  void Function(double)? onProgress,
  HttpClient? http,
}) async {
  if (url.scheme != 'https') {
    throw UpdateException('The download is not an https address.');
  }
  final client = http ?? HttpClient()
    ..connectionTimeout = const Duration(seconds: 10);
  final tmp = File('${dest.path}.part');
  try {
    final req = await client.getUrl(url);
    req.headers.set('User-Agent', 'bob-app');
    final res = await req.close().timeout(const Duration(seconds: 20));
    if (res.statusCode != 200) {
      await res.drain<void>();
      throw UpdateException('GitHub answered ${res.statusCode}.');
    }
    final total = res.contentLength;
    var got = 0;
    final sink = tmp.openWrite();
    final hash = _OneDigest();
    final hasher = sha256.startChunkedConversion(hash);
    try {
      await for (final chunk in res.timeout(const Duration(seconds: 30))) {
        sink.add(chunk);
        hasher.add(chunk);
        got += chunk.length;
        if (total > 0) onProgress?.call(got / total);
      }
    } finally {
      await sink.close();
    }
    hasher.close();
    if (total > 0 && got != total) {
      throw UpdateException('The download stopped part-way. Try again.');
    }
    final actual = hash.value.toString();
    if (sha256Hex != null && actual != sha256Hex.toLowerCase()) {
      throw UpdateException(
        "The download doesn't match the checksum GitHub published, so it was thrown away.",
      );
    }
    if (await dest.exists()) await dest.delete();
    await tmp.rename(dest.path);
    onProgress?.call(1);
  } on TimeoutException {
    throw UpdateException('The download timed out. Try again.');
  } finally {
    if (await tmp.exists()) {
      try {
        await tmp.delete();
      } catch (_) {}
    }
    if (http == null) client.close(force: true);
  }
}

/// The Bob.app folder that [executable] (".../Bob.app/Contents/MacOS/Bob") lives in, or null if it isn't inside an app.
String? appBundleFor(String executable) {
  final parts = executable.split('/');
  final i = parts.lastIndexWhere((p) => p.endsWith('.app'));
  if (i < 1) return null;
  return parts.take(i + 1).join('/');
}

String _q(String s) => "'${s.replaceAll("'", "'\\''")}'";

/// The shell script that waits for the running app to quit, swaps [newApp] in for [oldApp] (keeping the old one until the
/// new one is in place, and putting it back if anything fails), then opens the new one.
String macSwapScript({
  required int pid,
  required String oldApp,
  required String newApp,
  required String workDir,
  bool relaunch = true,
}) =>
    '''#!/bin/sh
# Written by the Bob app. Safe to delete.
i=0
while kill -0 $pid 2>/dev/null && [ \$i -lt 60 ]; do sleep 1; i=\$((i+1)); done
BACKUP=${_q('$oldApp.old')}
rm -rf "\$BACKUP"
if mv ${_q(oldApp)} "\$BACKUP"; then
  if mv ${_q(newApp)} ${_q(oldApp)}; then
    rm -rf "\$BACKUP"
  else
    mv "\$BACKUP" ${_q(oldApp)}
  fi
fi
rm -rf ${_q(workDir)}
${relaunch ? 'open ${_q(oldApp)}' : 'true'}
''';

abstract class AppInstaller {
  /// Installs the downloaded [file]. On the Mac the app quits and comes back by itself.
  Future<void> install(File file);
}

class AndroidInstaller implements AppInstaller {
  static const _channel = MethodChannel('bob/installer');
  @override
  Future<void> install(File file) async {
    try {
      final ok = await _channel.invokeMethod<bool>('installApk', {
        'path': file.path,
      });
      if (ok != true) {
        throw UpdateException(
          'Allow Bob to install apps in the settings page that just opened, then tap Update again.',
        );
      }
    } on PlatformException catch (e) {
      throw UpdateException(
        e.message ?? 'Android would not start the install.',
      );
    }
  }
}

class MacInstaller implements AppInstaller {
  MacInstaller({String? executable, int? pidOverride, this.quit})
    : _executable = executable ?? Platform.resolvedExecutable,
      _pid = pidOverride ?? pid;
  final String _executable;
  final int _pid;

  /// How to close the app once the swap script is running. Defaults to exiting the process.
  final void Function()? quit;

  @override
  Future<void> install(File zip) async {
    final old = appBundleFor(_executable);
    if (old == null) {
      throw UpdateException("This copy of Bob isn't running from an app file.");
    }
    final work = await Directory.systemTemp.createTemp('bob-update-');
    try {
      final unzip = await Process.run('/usr/bin/ditto', [
        '-x',
        '-k',
        zip.path,
        work.path,
      ]);
      if (unzip.exitCode != 0) {
        throw UpdateException("Couldn't unpack the update.");
      }
      final newApp = '${work.path}/Bob.app';
      if (!await Directory(newApp).exists()) {
        throw UpdateException('The update has no Bob.app inside.');
      }
      final check = await Process.run('/usr/bin/codesign', [
        '--verify',
        '--deep',
        newApp,
      ]);
      if (check.exitCode != 0) {
        throw UpdateException("The new app's signature didn't check out.");
      }
      // The folder holding the app must be writable, or the swap would fail after we quit.
      final probe = File('${File(old).parent.path}/.bob-write-test');
      try {
        await probe.writeAsString('x');
        await probe.delete();
      } catch (_) {
        throw UpdateException(
          "Bob can't write to ${File(old).parent.path}. Move Bob into Applications and try again.",
        );
      }
      final script = File('${work.path}/swap.sh');
      await script.writeAsString(
        macSwapScript(
          pid: _pid,
          oldApp: old,
          newApp: newApp,
          workDir: work.path,
        ),
      );
      await Process.start('/bin/sh', [
        script.path,
      ], mode: ProcessStartMode.detached);
    } catch (_) {
      try {
        await work.delete(recursive: true);
      } catch (_) {}
      rethrow;
    }
    (quit ?? () => exit(0))();
  }
}

AppInstaller? installerForThisDevice() => Platform.isAndroid
    ? AndroidInstaller()
    : Platform.isMacOS
    ? MacInstaller()
    : null;
