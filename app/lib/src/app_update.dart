import 'dart:convert';
import 'dart:io';

import 'package:url_launcher/url_launcher.dart';

/// The version of this app. Keep it equal to `version:` in pubspec.yaml (a test checks).
const appVersion = '26.10.2';

const releasesApi =
    'https://api.github.com/repos/TECWiSaRd/Bob-Cena/releases/latest';

/// The newest published release: its version, the file for this kind of device, and the page to read about it.
class ReleaseInfo {
  const ReleaseInfo({
    required this.version,
    required this.page,
    this.download,
    this.notes = '',
  });
  final String version;
  final Uri page;
  final Uri?
  download; // the Mac zip or Android APK; null when the release has no file for this device
  final String notes;
}

/// "v26.10.2" and "26.10.2" are the same version. Null when it isn't dotted numbers.
List<int>? parseVersion(String text) {
  final t = text.trim().replaceFirst(RegExp(r'^[vV]'), '');
  final m = RegExp(r'^\d+(\.\d+)*').firstMatch(t);
  if (m == null) return null;
  return m.group(0)!.split('.').map(int.parse).toList();
}

/// True when [latest] is newer than [current]. A version that can't be read is never "newer".
bool isNewer(String latest, String current) {
  final a = parseVersion(latest), b = parseVersion(current);
  if (a == null || b == null) return false;
  for (var i = 0; i < (a.length > b.length ? a.length : b.length); i++) {
    final x = i < a.length ? a[i] : 0, y = i < b.length ? b[i] : 0;
    if (x != y) return x > y;
  }
  return false;
}

/// Reads GitHub's "latest release" answer. [assetName] is the file for this device ("Bob-mac.zip" or "Bob-android.apk").
ReleaseInfo? parseRelease(Object? json, String? assetName) {
  if (json is! Map) return null;
  final tag = json['tag_name']?.toString() ?? '';
  final page = Uri.tryParse(json['html_url']?.toString() ?? '');
  if (parseVersion(tag) == null || page == null || page.scheme != 'https') {
    return null;
  }
  Uri? download;
  for (final a in (json['assets'] as List?) ?? const []) {
    if (a is Map && a['name'] == assetName) {
      final u = Uri.tryParse(a['browser_download_url']?.toString() ?? '');
      if (u != null && u.scheme == 'https') download = u;
    }
  }
  return ReleaseInfo(
    version: tag.replaceFirst(RegExp(r'^[vV]'), ''),
    page: page,
    download: download,
    notes: (json['body'] ?? '').toString().trim(),
  );
}

String? assetForThisDevice() => Platform.isMacOS
    ? 'Bob-mac.zip'
    : Platform.isAndroid
    ? 'Bob-android.apk'
    : null;

/// Asks GitHub for the newest release. Uses the system's normal certificate checks (this is GitHub, not Bob).
Future<ReleaseInfo?> fetchLatestRelease({
  HttpClient? http,
  String? assetName,
}) async {
  final client = http ?? HttpClient()
    ..connectionTimeout = const Duration(seconds: 8);
  try {
    final req = await client
        .getUrl(Uri.parse(releasesApi))
        .timeout(const Duration(seconds: 10));
    req.headers
      ..set('Accept', 'application/vnd.github+json')
      ..set('User-Agent', 'bob-app/$appVersion');
    final res = await req.close().timeout(const Duration(seconds: 10));
    if (res.statusCode != 200) {
      await res.drain<void>();
      throw HttpException('GitHub answered ${res.statusCode}');
    }
    final body = await res
        .transform(utf8.decoder)
        .join()
        .timeout(const Duration(seconds: 10));
    return parseRelease(jsonDecode(body), assetName ?? assetForThisDevice());
  } finally {
    if (http == null) client.close(force: true);
  }
}

/// Opens a web address in the browser (which downloads the file; a Mac or phone then asks before opening it).
Future<bool> openInBrowser(Uri uri) =>
    launchUrl(uri, mode: LaunchMode.externalApplication);
