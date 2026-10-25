import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';

import 'mjpeg.dart';
import 'pairing.dart';
import 'profile.dart';

class BobApiException implements Exception {
  BobApiException(this.status, this.message);
  final int status;
  final String message;
  bool get unauthorized => status == 401;
  @override
  String toString() => message;
}

/// Talks to one Bob over HTTPS, accepting only the certificate it was paired with.
///
/// Before pairing there is nothing to pin yet, so the first certificate seen is remembered and every later connection in the
/// same pairing must present the same one; the pairing proof then ties that certificate to the code on Bob's console, which a
/// man in the middle cannot know.
class BobClient {
  BobClient({
    required this.host,
    required this.port,
    this.pinnedFingerprint,
    this.token,
  });

  factory BobClient.fromProfile(BobProfile p) => BobClient(
    host: p.host,
    port: p.port,
    pinnedFingerprint: p.fingerprint,
    token: p.token,
  );

  final String host;
  final int port;
  final String? pinnedFingerprint;
  final String? token;

  /// The fingerprint of the certificate seen on the first connection (used while pairing).
  String? seenFingerprint;
  bool certificateRejected = false;

  late final HttpClient _http = _makeHttp();
  final List<HttpClient> _streamClients = [];

  HttpClient _makeHttp() {
    final c = HttpClient()..connectionTimeout = const Duration(seconds: 6);
    c.badCertificateCallback = (X509Certificate cert, String h, int p) {
      final fp = sha256.convert(cert.der).toString();
      final expected = pinnedFingerprint ?? seenFingerprint;
      if (expected == null) {
        seenFingerprint = fp;
        return true;
      }
      final ok = fp == expected;
      if (!ok) certificateRejected = true;
      return ok;
    };
    return c;
  }

  Uri _uri(String path) =>
      Uri(scheme: 'https', host: host, port: port, path: path);

  Future<Map<String, dynamic>> _json(
    String method,
    String path, {
    Map<String, dynamic>? body,
    bool auth = true,
  }) async {
    final req = await _http
        .openUrl(method, _uri(path))
        .timeout(const Duration(seconds: 8));
    if (auth && token != null) {
      req.headers.set('Authorization', 'Bearer $token');
    }
    if (body != null) {
      // Bob's server wants a Content-Length (Dart sends chunked bodies unless told the size).
      final bytes = utf8.encode(jsonEncode(body));
      req.headers.contentType = ContentType.json;
      req.contentLength = bytes.length;
      req.add(bytes);
    }
    final resp = await req.close().timeout(const Duration(seconds: 10));
    final text = await resp
        .transform(utf8.decoder)
        .join()
        .timeout(const Duration(seconds: 10));
    Map<String, dynamic> data;
    try {
      data = jsonDecode(text) as Map<String, dynamic>;
    } catch (_) {
      data = {'error': text.isEmpty ? 'no answer' : text};
    }
    if (resp.statusCode >= 400) {
      throw BobApiException(
        resp.statusCode,
        (data['error'] ?? 'error ${resp.statusCode}').toString(),
      );
    }
    return data;
  }

  Future<Map<String, dynamic>> info() =>
      _json('GET', '/api/v1/info', auth: false);

  /// Pairs this device using the code shown on Bob's console. Returns the profile to keep.
  Future<BobProfile> pair(String code, String deviceName) async {
    final information =
        await info(); // also records the certificate we are being shown
    final seen = seenFingerprint;
    if (seen == null) {
      throw BobApiException(0, 'could not read his certificate');
    }
    final nonce = newNonce();
    final reply = await _json(
      'POST',
      '/api/v1/pair',
      body: {
        'device': deviceName,
        'nonce': nonce,
        'proof': clientProof(code, nonce, seen),
      },
      auth: false,
    );
    final token = reply['token'] as String;
    // Bob proves he knew the code, saw the same certificate, and issued exactly this token.
    final expected = serverProof(code, nonce, seen, token);
    if (reply['server_proof'] != expected || reply['fingerprint'] != seen) {
      throw BobApiException(
        0,
        'his answer did not check out: this may not be your Bob. Nothing was saved.',
      );
    }
    return BobProfile(
      name: (reply['name'] ?? information['name'] ?? 'Bob').toString(),
      host: host,
      port: port,
      fingerprint: seen,
      token: token,
      device: (reply['device'] ?? deviceName).toString(),
    );
  }

  Future<Map<String, dynamic>> status() => _json('GET', '/api/v1/status');

  Future<String> command(String text) async =>
      ((await _json('POST', '/api/v1/cmd', body: {'cmd': text}))['output'] ??
              '')
          .toString();

  Future<void> drive(double left, double right) =>
      _json('POST', '/api/v1/drive', body: {'left': left, 'right': right});

  Future<void> unpair() => _json('POST', '/api/v1/unpair', body: {});

  /// Bob's camera, as a stream of JPEG pictures. Cancel the subscription to stop.
  Stream<Uint8List> video() async* {
    final client = _makeHttp();
    _streamClients.add(client);
    try {
      final req = await client
          .openUrl('GET', _uri('/api/v1/stream'))
          .timeout(const Duration(seconds: 8));
      if (token != null) req.headers.set('Authorization', 'Bearer $token');
      final resp = await req.close().timeout(const Duration(seconds: 10));
      if (resp.statusCode != 200) {
        throw BobApiException(resp.statusCode, 'no video (${resp.statusCode})');
      }
      final parser = MjpegParser();
      await for (final chunk in resp) {
        for (final frame in parser.add(chunk)) {
          yield frame;
        }
      }
    } finally {
      client.close(force: true);
      _streamClients.remove(client);
    }
  }

  void close() {
    _http.close(force: true);
    for (final c in List.of(_streamClients)) {
      c.close(force: true);
    }
  }
}
