import 'dart:async';
import 'dart:io' show Platform;

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'app_state.dart';
import 'client.dart';
import 'discovery.dart';
import 'pairing.dart';

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
  final _device = TextEditingController(text: 'My ${_platformName()}');
  FoundBob? _picked;
  bool _busy = false;
  String? _error;

  static String _platformName() => Platform.isMacOS ? 'Mac' : Platform.isAndroid ? 'Android phone' : 'device';

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
    _device.dispose();
    super.dispose();
  }

  (String, int)? _target() {
    if (_picked != null) return (_picked!.host, _picked!.port);
    final text = _address.text.trim();
    if (text.isEmpty) return null;
    final i = text.lastIndexOf(':');
    if (i > 0 && int.tryParse(text.substring(i + 1)) != null) {
      return (text.substring(0, i), int.parse(text.substring(i + 1)));
    }
    return (text, 8443);
  }

  Future<void> _pair() async {
    final target = _target();
    if (target == null) {
      setState(() => _error = "Choose a Bob from the list or type his address (for example bobcena.local:8443).");
      return;
    }
    if (normalizeCode(_code.text).length != 12) {
      setState(() => _error = 'The code has 12 letters and numbers. Type /pair in Bob\'s console to get one.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    final state = context.read<AppState>();
    final client = BobClient(host: target.$1, port: target.$2);
    try {
      final profile = await client.pair(_code.text, _device.text.trim().isEmpty ? 'device' : _device.text.trim());
      await state.setProfile(profile);
    } on BobApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } catch (e) {
      if (mounted) setState(() => _error = "Couldn't reach ${target.$1}:${target.$2}. Is Bob on, and on the same network?");
    } finally {
      client.close();
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Add Bob')),
      body: SafeArea(
        child: ListView(padding: const EdgeInsets.all(16), children: [
          const Text('1. On Bob\'s console (or the shared console) type  /pair  to get a one-time code.',
              style: TextStyle(fontSize: 15)),
          const SizedBox(height: 16),
          Text('2. Choose Bob', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          if (_found.isEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Text(_discovery.error ?? 'Looking for Bob on this network...',
                  style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant)),
            ),
          for (final b in _found)
            ListTile(
              selected: _picked?.id == b.id,
              leading: Icon(_picked?.id == b.id ? Icons.radio_button_checked : Icons.radio_button_unchecked),
              onTap: _busy ? null : () => setState(() => _picked = b),
              title: Text(b.name),
              subtitle: Text(b.id),
            ),
          const SizedBox(height: 8),
          TextField(
            controller: _address,
            enabled: !_busy,
            decoration: const InputDecoration(
                labelText: 'or type his address', hintText: 'bobcena.local:8443', border: OutlineInputBorder()),
            onChanged: (_) => setState(() => _picked = null),
          ),
          const SizedBox(height: 16),
          Text('3. Enter the code', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          TextField(
            controller: _code,
            enabled: !_busy,
            textCapitalization: TextCapitalization.characters,
            autocorrect: false,
            style: const TextStyle(fontSize: 22, letterSpacing: 2, fontFeatures: [FontFeature.tabularFigures()]),
            decoration: const InputDecoration(labelText: 'pairing code', hintText: 'K7PQ-2M9X-4TWD', border: OutlineInputBorder()),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _device,
            enabled: !_busy,
            decoration: const InputDecoration(labelText: 'a name for this device', border: OutlineInputBorder()),
          ),
          const SizedBox(height: 16),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
            ),
          FilledButton(
            onPressed: _busy ? null : _pair,
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: _busy
                  ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Text('Pair'),
            ),
          ),
          const SizedBox(height: 12),
          Text(
            'The code is never sent over the network. The app and Bob each prove they know it, and the app then '
            'trusts only Bob\'s own certificate.',
            style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant, fontSize: 12),
          ),
        ]),
      ),
    );
  }
}
