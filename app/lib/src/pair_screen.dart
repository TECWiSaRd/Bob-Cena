import 'dart:async';
import 'dart:io' show Platform;

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'app_state.dart';
import 'client.dart';
import 'design.dart';
import 'discovery.dart';
import 'pairing.dart';
import 'theme.dart';

/// Adding Bob: find him on the network (or type his address), then enter the one-time code from his console.
class PairScreen extends StatefulWidget {
  const PairScreen({super.key, this.discovery});
  final BobDiscovery? discovery; // injectable for tests

  @override
  State<PairScreen> createState() => _PairScreenState();
}

class _PairScreenState extends State<PairScreen> {
  late final BobDiscovery _discovery = widget.discovery ?? BobDiscovery();
  StreamSubscription<List<FoundBob>>? _sub;
  List<FoundBob> _found = [];
  final _address = TextEditingController();
  final _code = TextEditingController();
  final _user = TextEditingController();
  final _device = TextEditingController(text: 'My ${_platformName()}');
  FoundBob? _picked;
  bool _busy = false;
  String? _error;

  static String _platformName() => Platform.isMacOS
      ? 'Mac'
      : Platform.isAndroid
      ? 'Android phone'
      : 'device';

  @override
  void initState() {
    super.initState();
    _sub = _discovery.results.listen((list) => setState(() => _found = list));
    unawaited(_discovery.start());
  }

  @override
  void dispose() {
    _sub?.cancel();
    unawaited(_discovery.stop());
    _address.dispose();
    _code.dispose();
    _user.dispose();
    _device.dispose();
    super.dispose();
  }

  String _why = '';

  (String, int)? _target() {
    if (_picked != null) return (_picked!.host, _picked!.port);
    final text = _address.text.trim();
    if (text.isEmpty) {
      _why = '';
      return null;
    }
    final a = parseBobAddress(text);
    _why = a.error ?? '';
    return a.host == null ? null : (a.host!, a.port);
  }

  Future<void> _pair() async {
    final target = _target();
    if (target == null) {
      setState(
        () => _error =
            '${_why.isEmpty ? '' : '$_why '}Choose a Bob from the list or type his address (for example bobcena.local:8443 or [fd00::1]:8443).',
      );
      return;
    }
    if (normalizeCode(_code.text).length != 12) {
      setState(
        () => _error =
            'The code has 12 letters and numbers. Type /pair in Bob\'s console to get one.',
      );
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    final state = context.read<AppState>();
    final client = BobClient(host: target.$1, port: target.$2);
    try {
      final profile = await client.pair(
        _code.text,
        _device.text.trim().isEmpty ? 'device' : _device.text.trim(),
      );
      await state.setProfile(
        profile.copyWith(
          user: _user.text.trim().isEmpty ? null : _user.text.trim(),
        ),
      );
    } on BobApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } catch (e) {
      if (mounted) {
        setState(
          () => _error =
              "Couldn't reach ${target.$1}:${target.$2}. Is Bob on, and on the same network?",
        );
      }
    } finally {
      client.close();
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 24, 20, 32),
          children: [
            const Center(
              child: BobHeader(
                online: false,
                problem: 'not paired yet',
                compact: true,
              ),
            ),
            const SizedBox(height: 12),
            Center(
              child: Text(
                'Add Bob',
                style: TextStyle(
                  fontFamily: BobFonts.script,
                  fontSize: 60,
                  height: 1.1,
                  color: Theme.of(context).colorScheme.onSurface,
                ),
              ),
            ),
            const SizedBox(height: 12),
            const Text(
              '1. On Bob\'s console (or the shared console) type  /pair  to get a one-time code.',
              style: TextStyle(fontSize: 15),
            ),
            const SizedBox(height: 16),
            Text(
              '2. Choose Bob',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            if (_found.isEmpty)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Text(
                  _discovery.error ?? 'Looking for Bob on this network...',
                  style: TextStyle(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
                ),
              ),
            for (final b in _found)
              ListTile(
                selected: _picked?.id == b.id,
                leading: Icon(
                  _picked?.id == b.id
                      ? Icons.radio_button_checked
                      : Icons.radio_button_unchecked,
                ),
                onTap: _busy ? null : () => setState(() => _picked = b),
                title: Text(b.name),
                subtitle: Text(b.id),
              ),
            const SizedBox(height: 8),
            TextField(
              controller: _address,
              enabled: !_busy,
              decoration: const InputDecoration(
                labelText: 'or type his address',
                hintText: 'bobcena.local:8443 or [fd00::1]:8443',
              ),
              onChanged: (_) => setState(() => _picked = null),
            ),
            const SizedBox(height: 16),
            Text(
              '3. Enter the code',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            TextField(
              controller: _code,
              enabled: !_busy,
              textCapitalization: TextCapitalization.characters,
              autocorrect: false,
              style: const TextStyle(
                fontSize: 22,
                letterSpacing: 2,
                fontFeatures: [FontFeature.tabularFigures()],
              ),
              decoration: const InputDecoration(
                labelText: 'pairing code',
                hintText: 'K7PQ-2M9X-4TWD',
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _device,
              enabled: !_busy,
              decoration: const InputDecoration(
                labelText: 'a name for this device',
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _user,
              enabled: !_busy,
              textCapitalization: TextCapitalization.words,
              decoration: const InputDecoration(
                labelText: 'your name (for the welcome)',
                hintText: 'Adam',
              ),
            ),
            const SizedBox(height: 16),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Text(
                  _error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ),
            FilledButton(
              onPressed: _busy ? null : _pair,
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: _busy
                    ? const SizedBox(
                        height: 20,
                        width: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Text('Pair'),
              ),
            ),
            const SizedBox(height: 12),
            Text(
              'The code is never sent over the network. The app and Bob each prove they know it, and the app then '
              'trusts only Bob\'s own certificate.',
              style: TextStyle(
                color: Theme.of(context).colorScheme.onSurfaceVariant,
                fontSize: 12,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// What the address box held: a host and port, or the reason it was refused.
class BobAddress {
  const BobAddress.ok(String this.host, this.port) : error = null;
  const BobAddress.bad(String this.error) : host = null, port = 8443;
  final String? host;
  final int port;
  final String? error;
}

final _hostName = RegExp(r'^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$');
final _ipv6 = RegExp(r'^[0-9A-Fa-f:.]+$');

/// Reads "bobcena.local", "bobcena.local:8443", "192.168.1.5:8443", "[fd00::1]:8443" or a bare "fd00::1". Bob's usual port
/// (8443) is used when none is given. A pasted "https://" is accepted and dropped.
BobAddress parseBobAddress(String input) {
  var text = input.trim();
  text = text.replaceFirst(RegExp(r'^https?://', caseSensitive: false), '');
  text = text.replaceFirst(RegExp(r'/+$'), '');
  if (text.isEmpty) return const BobAddress.bad('The address is empty.');
  if (RegExp(r'\s').hasMatch(text) || text.contains('/')) {
    return const BobAddress.bad('The address has spaces or a path in it.');
  }
  if (text.contains('%')) {
    return const BobAddress.bad(
      "Addresses with a zone (like fe80::1%en0) aren't supported. Use Bob's name (bobcena.local) or his normal address.",
    );
  }
  int? port(String raw) {
    if (!RegExp(r'^\d{1,5}$').hasMatch(raw)) return null;
    final v = int.parse(raw);
    return v >= 1 && v <= 65535 ? v : null;
  }

  String host;
  var p = 8443;
  if (text.startsWith('[')) {
    final end = text.indexOf(']');
    if (end <= 1) return const BobAddress.bad('The [brackets] are not closed.');
    host = text.substring(1, end);
    final rest = text.substring(end + 1);
    if (rest.isNotEmpty) {
      if (!rest.startsWith(':')) {
        return const BobAddress.bad(
          'Put the port after the brackets: [fd00::1]:8443.',
        );
      }
      final v = port(rest.substring(1));
      if (v == null) {
        return BobAddress.bad(
          '"${rest.substring(1)}" is not a port number (1 to 65535).',
        );
      }
      p = v;
    }
    if (!host.contains(':') || !_ipv6.hasMatch(host)) {
      return const BobAddress.bad('That is not an IPv6 address.');
    }
    return BobAddress.ok(host, p);
  }
  final colons = ':'.allMatches(text).length;
  if (colons > 1) {
    // A bare IPv6 address always uses the usual port; a port needs brackets.
    if (!_ipv6.hasMatch(text)) {
      return const BobAddress.bad('That is not an address.');
    }
    return BobAddress.ok(text, p);
  }
  if (colons == 1) {
    final i = text.indexOf(':');
    host = text.substring(0, i);
    final after = text.substring(i + 1);
    // "bob.local:" is a common slip: use the usual port rather than refuse.
    if (after.isNotEmpty) {
      final v = port(after);
      if (v == null) {
        return BobAddress.bad('"$after" is not a port number (1 to 65535).');
      }
      p = v;
    }
  } else {
    host = text;
  }
  if (host.isEmpty) {
    return const BobAddress.bad('The address is missing its host name.');
  }
  if (!_hostName.hasMatch(host)) {
    return BobAddress.bad('"$host" is not a valid host name.');
  }
  return BobAddress.ok(host, p);
}
