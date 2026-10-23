import 'dart:convert';
import 'dart:math';

import 'package:crypto/crypto.dart';

/// The pairing proofs. These must match appapi.py on Bob exactly: the code itself is never sent, only proofs of knowing it.
String normalizeCode(String text) => text.toUpperCase().replaceAll(RegExp(r'[^A-Z0-9]'), '');

String _hmacHex(String key, String message) =>
    Hmac(sha256, utf8.encode(key)).convert(utf8.encode(message)).toString();

/// What the app sends: proves it knows the code, and binds the proof to the certificate it was shown.
String clientProof(String code, String nonce, String fingerprint) =>
    _hmacHex(normalizeCode(code), 'pair-client|$nonce|$fingerprint');

/// What Bob answers with: proves HE knows the code, saw the same certificate, and issued this token.
String serverProof(String code, String nonce, String fingerprint, String token) =>
    _hmacHex(normalizeCode(code), 'pair-server|$nonce|$fingerprint|$token');

/// A fresh random value (URL-safe) used once per pairing attempt.
String newNonce([Random? random]) {
  final r = random ?? Random.secure();
  return base64Url.encode(List<int>.generate(12, (_) => r.nextInt(256))).replaceAll('=', '');
}

/// 'k7pq2m9x4twd' -> 'K7PQ-2M9X-4TWD'
String showCode(String text) {
  final c = normalizeCode(text);
  final parts = <String>[];
  for (var i = 0; i < c.length; i += 4) {
    parts.add(c.substring(i, min(i + 4, c.length)));
  }
  return parts.join('-');
}
