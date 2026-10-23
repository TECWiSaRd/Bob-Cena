import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';

import 'client.dart';

/// Bob's live camera. Reconnects by itself if the stream drops.
class MjpegView extends StatefulWidget {
  const MjpegView({super.key, required this.client});
  final BobClient client;

  @override
  State<MjpegView> createState() => _MjpegViewState();
}

class _MjpegViewState extends State<MjpegView> {
  StreamSubscription<Uint8List>? _sub;
  Uint8List? _frame;
  String? _error;
  bool _disposed = false;

  @override
  void initState() {
    super.initState();
    _connect();
  }

  void _connect() {
    _sub?.cancel();
    _sub = widget.client.video().listen(
      (f) {
        if (!mounted) return;
        setState(() {
          _frame = f;
          _error = null;
        });
      },
      onError: (Object e) {
        if (mounted) setState(() => _error = e.toString());
        _retry();
      },
      onDone: () {
        if (mounted) setState(() => _error ??= 'The picture stopped');
        _retry();
      },
      cancelOnError: true,
    );
  }

  void _retry() {
    Future<void>.delayed(const Duration(seconds: 3), () {
      if (!_disposed && mounted) _connect();
    });
  }

  @override
  void didUpdateWidget(MjpegView old) {
    super.didUpdateWidget(old);
    if (old.client != widget.client) _connect();
  }

  @override
  void dispose() {
    _disposed = true;
    _sub?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AspectRatio(
      aspectRatio: 4 / 3,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(12),
        child: Container(
          color: Colors.black,
          child: _frame == null
              ? Center(
                  child: Text(_error ?? 'Waiting for the picture...',
                      textAlign: TextAlign.center, style: const TextStyle(color: Colors.white70)))
              : Image.memory(_frame!, gaplessPlayback: true, fit: BoxFit.contain),
        ),
      ),
    );
  }
}

/// A thumb stick. Reports x (right is positive) and y (forward is positive), each from -1 to 1; (0, 0) when let go.
class Joystick extends StatefulWidget {
  const Joystick({super.key, required this.onChanged, this.size = 200});
  final void Function(double x, double y) onChanged;
  final double size;

  @override
  State<Joystick> createState() => _JoystickState();
}

class _JoystickState extends State<Joystick> {
  Offset _knob = Offset.zero; // -1..1 in both directions

  void _update(Offset local) {
    final r = widget.size / 2;
    var v = (local - Offset(r, r)) / r;
    if (v.distance > 1) v = v / v.distance;
    setState(() => _knob = v);
    widget.onChanged(v.dx, -v.dy);
  }

  void _release() {
    setState(() => _knob = Offset.zero);
    widget.onChanged(0, 0);
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final r = widget.size / 2;
    return SizedBox(
      width: widget.size,
      height: widget.size,
      child: GestureDetector(
        onPanStart: (d) => _update(d.localPosition),
        onPanUpdate: (d) => _update(d.localPosition),
        onPanEnd: (_) => _release(),
        onPanCancel: _release,
        child: Stack(children: [
          Container(
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: scheme.surfaceContainerHighest,
              border: Border.all(color: scheme.outlineVariant, width: 2),
            ),
          ),
          Positioned(
            left: r + _knob.dx * r * 0.7 - 32,
            top: r + _knob.dy * r * 0.7 - 32,
            child: Container(
              width: 64,
              height: 64,
              decoration: BoxDecoration(shape: BoxShape.circle, color: scheme.primary.withValues(alpha: 0.9)),
            ),
          ),
        ]),
      ),
    );
  }
}

/// The two wheel speeds for a stick position (arcade mixing, never above full speed).
(double, double) mixWheels(double x, double y, {double scale = 1.0}) {
  var left = y + x;
  var right = y - x;
  final peak = [left.abs(), right.abs(), 1.0].reduce((a, b) => a > b ? a : b);
  left = left / peak * scale;
  right = right / peak * scale;
  return (left, right);
}

class StatChip extends StatelessWidget {
  const StatChip(this.text, {super.key, this.color});
  final String text;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final c = color ?? Theme.of(context).colorScheme.onSurfaceVariant;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(border: Border.all(color: c.withValues(alpha: 0.5)), borderRadius: BorderRadius.circular(99)),
      child: Text(text, style: TextStyle(color: c, fontSize: 12)),
    );
  }
}
