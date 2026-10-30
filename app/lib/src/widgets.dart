import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';

import 'client.dart';
import 'theme.dart';

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
        borderRadius: BorderRadius.circular(32),
        child: Container(
          color: Colors.black,
          child: _frame == null
              ? Center(
                  child: Text(
                    _error ?? 'Waiting for the picture...',
                    textAlign: TextAlign.center,
                    style: const TextStyle(color: Colors.white70),
                  ),
                )
              : Image.memory(
                  _frame!,
                  gaplessPlayback: true,
                  fit: BoxFit.contain,
                ),
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
  int? _pointer; // the finger that owns the stick; others are ignored
  bool _stopped = true; // the last thing reported was (0, 0)

  void _report(double x, double y) {
    final stop = x == 0 && y == 0;
    if (stop && _stopped) {
      return; // a resting thumb must not repeat "stop" on every tiny move
    }
    _stopped = stop;
    widget.onChanged(x, y);
  }

  void _update(Offset local) {
    final r = widget.size / 2;
    var v = (local - Offset(r, r)) / r;
    if (v.distance > 1) v = v / v.distance;
    setState(() => _knob = v);
    // A small circle in the middle counts as centred, so a resting thumb doesn't creep.
    final still = v.distance < 0.08;
    _report(still ? 0 : v.dx, still ? 0 : -v.dy);
  }

  void _release() {
    _pointer = null;
    setState(() => _knob = Offset.zero);
    _report(0, 0);
  }

  @override
  void dispose() {
    // If the stick leaves the screen with a finger on it (a disconnect, a mode change, a page change), no pointer-up
    // will ever arrive, so the last drive command would stay in force. Say stop.
    if (_pointer != null) widget.onChanged(0, 0);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final r = widget.size / 2;
    // Raw touches, not a pan gesture: a pan only starts after the finger has moved a little, and a stick inside a
    // scrolling page loses forward and backward drags to the page. The eager recognizer claims the touch at once so
    // the page can't scroll while the stick is held; the listener then reads the finger from the first instant.
    // ClipOval makes only the round pad touchable; the square's corners are ignored (and don't block scrolling).
    return ClipOval(
      clipBehavior: Clip.none,
      child: RawGestureDetector(
        behavior: HitTestBehavior.opaque,
        gestures: {
          EagerGestureRecognizer:
              GestureRecognizerFactoryWithHandlers<EagerGestureRecognizer>(
                EagerGestureRecognizer.new,
                (_) {},
              ),
        },
        child: Listener(
          behavior: HitTestBehavior.opaque,
          onPointerDown: (e) {
            if (_pointer != null) return;
            _pointer = e.pointer;
            _update(e.localPosition);
          },
          onPointerMove: (e) {
            if (e.pointer == _pointer) _update(e.localPosition);
          },
          onPointerUp: (e) {
            if (e.pointer == _pointer) _release();
          },
          onPointerCancel: (e) {
            if (e.pointer == _pointer) _release();
          },
          child: SizedBox(
            width: widget.size,
            height: widget.size,
            child: Stack(
              children: [
                Container(
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: scheme.surface,
                    border: Border.all(
                      color: scheme.onSurface.withValues(alpha: 0.12),
                      width: 2,
                    ),
                  ),
                ),
                Positioned(
                  left: r + _knob.dx * r * 0.7 - 32,
                  top: r + _knob.dy * r * 0.7 - 32,
                  child: Container(
                    width: 64,
                    height: 64,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: scheme.primary.withValues(alpha: 0.9),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
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
      decoration: BoxDecoration(
        border: Border.all(color: c.withValues(alpha: 0.5)),
        borderRadius: BorderRadius.circular(99),
      ),
      child: Text(text, style: TextStyle(color: c, fontSize: 12)),
    );
  }
}

/// A pill that is on or off, and shows which. Tapping it flips it.
class TogglePill extends StatelessWidget {
  const TogglePill({
    super.key,
    required this.label,
    required this.icon,
    required this.selected,
    required this.onChanged,
    this.danger = false,
  });
  final String label;
  final IconData icon;
  final bool selected;
  final void Function(bool value) onChanged;
  final bool danger; // red when on (the emergency stop)

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final on = danger ? BobColors.red : scheme.primary;
    return Semantics(
      toggled: selected,
      button: true,
      label: label,
      child: FilterChip(
        label: Text(label),
        avatar: Icon(
          icon,
          size: 20,
          color: selected ? Colors.white : scheme.onSurface,
        ),
        selected: selected,
        showCheckmark: false,
        selectedColor: on,
        backgroundColor: scheme.surface,
        labelStyle: TextStyle(
          fontSize: 15,
          fontWeight: FontWeight.w600,
          color: selected ? Colors.white : scheme.onSurface,
        ),
        side: BorderSide(
          color: selected ? on : scheme.onSurface.withValues(alpha: 0.15),
        ),
        shape: const StadiumBorder(),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 12),
        onSelected: onChanged,
      ),
    );
  }
}
