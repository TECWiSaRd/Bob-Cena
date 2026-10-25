import 'dart:async';
import 'dart:convert';

import 'package:nsd/nsd.dart' as nsd;

class FoundBob {
  FoundBob({
    required this.name,
    required this.host,
    required this.port,
    this.fingerprintPrefix,
  });
  final String name;
  final String host;
  final int port;
  final String?
  fingerprintPrefix; // the first 16 hex digits of his certificate, to recognise him again

  String get id => '$host:$port';
}

/// Finds Bobs on the local network by listening for his Bonjour announcement (_bob._tcp).
class BobDiscovery {
  nsd.Discovery? _discovery;
  final _found = <String, FoundBob>{};
  final _controller = StreamController<List<FoundBob>>.broadcast();
  String? error;

  Stream<List<FoundBob>> get results => _controller.stream;
  List<FoundBob> get current => _found.values.toList();

  Future<void> start() async {
    try {
      final d = await nsd.startDiscovery(
        '_bob._tcp',
        ipLookupType: nsd.IpLookupType.any,
      );
      _discovery = d;
      d.addServiceListener((service, status) async {
        if (status == nsd.ServiceStatus.found) {
          try {
            final resolved = await nsd.resolve(service);
            final host = _bestAddress(resolved);
            final port = resolved.port;
            if (host == null || port == null) return;
            final fpBytes = resolved.txt?['fp'];
            final bob = FoundBob(
              name: resolved.name ?? 'Bob',
              host: host,
              port: port,
              fingerprintPrefix: fpBytes == null
                  ? null
                  : utf8.decode(fpBytes, allowMalformed: true),
            );
            _found[service.name ?? bob.id] = bob;
          } catch (_) {
            return;
          }
        } else {
          _found.remove(service.name);
        }
        if (!_controller.isClosed) _controller.add(current);
      });
    } catch (e) {
      error =
          'Automatic discovery is not available here ($e). Enter his address instead.';
      if (!_controller.isClosed) _controller.add(current);
    }
  }

  static String? _bestAddress(nsd.Service s) {
    final addresses = s.addresses;
    if (addresses != null && addresses.isNotEmpty) {
      // prefer IPv4: a plain address works everywhere, a link-local IPv6 one needs a scope id
      final v4 = addresses.where((a) => a.type.name == 'IPv4');
      return (v4.isNotEmpty ? v4.first : addresses.first).address;
    }
    return s.host;
  }

  Future<void> stop() async {
    final d = _discovery;
    _discovery = null;
    if (d != null) {
      try {
        await nsd.stopDiscovery(d);
      } catch (_) {}
    }
    await _controller.close();
  }
}
