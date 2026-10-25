import 'dart:async';
import 'dart:io' show Platform;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import 'app_state.dart';
import 'widgets.dart';

const _bottomRoom = 210.0; // keeps content clear of the emergency stop button

Future<void> runCommand(
  BuildContext context,
  String text, {
  bool dialogIfLong = true,
}) async {
  final s = context.read<AppState>();
  final messenger = ScaffoldMessenger.of(context);
  try {
    final out = (await s.send(text)).trim();
    if (out.isEmpty || !context.mounted) return;
    if (dialogIfLong && (out.length > 90 || out.contains('\n'))) {
      await showDialog<void>(
        context: context,
        builder: (c) => AlertDialog(
          title: Text(text.split(' ').first),
          content: SingleChildScrollView(
            child: SelectableText(
              out,
              style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(c),
              child: const Text('OK'),
            ),
          ],
        ),
      );
    } else {
      messenger.showSnackBar(SnackBar(content: Text(out)));
    }
  } catch (e) {
    messenger.showSnackBar(SnackBar(content: Text(e.toString())));
  }
}

/// Flip a setting on Bob: the switch changes at once, and Bob's answer (if any) is shown. Flips back if he can't be reached.
Future<void> flip(
  BuildContext context,
  Map<String, dynamic> patch,
  String command,
) async {
  final s = context.read<AppState>();
  final messenger = ScaffoldMessenger.of(context);
  try {
    final out = (await s.toggle(patch, command)).trim();
    if (out.isNotEmpty && context.mounted) {
      messenger.showSnackBar(SnackBar(content: Text(out)));
    }
  } catch (e) {
    messenger.showSnackBar(SnackBar(content: Text(e.toString())));
  }
}

/// The on/off controls. [all] adds the ones that belong on the More page; the Drive page shows just the two it needs.
class ControlToggles extends StatelessWidget {
  const ControlToggles({super.key, this.all = false});
  final bool all;

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      alignment: all ? WrapAlignment.start : WrapAlignment.center,
      children: [
        TogglePill(
          key: const Key('toggle-ai'),
          label: 'AI thinking',
          icon: Icons.psychology,
          selected: s.aiOn,
          onChanged: (v) =>
              flip(context, {'auto': v}, v ? '/resume' : '/pause'),
        ),
        TogglePill(
          key: const Key('toggle-follow'),
          label: 'Follow me',
          icon: Icons.directions_walk,
          selected: s.following,
          onChanged: (v) =>
              flip(context, {'follow': v}, v ? '/follow 30' : '/follow off'),
        ),
        if (all) ...[
          TogglePill(
            key: const Key('toggle-sleep'),
            label: 'Sleep',
            icon: Icons.bedtime,
            selected: s.sleeping,
            onChanged: (v) =>
                flip(context, {'sleep': v}, v ? '/sleep on' : '/sleep off'),
          ),
          TogglePill(
            key: const Key('toggle-sound'),
            label: 'Sound',
            icon: s.soundOn ? Icons.volume_up : Icons.volume_off,
            selected: s.soundOn,
            onChanged: (v) =>
                flip(context, {'muted': !v}, v ? '/unmute' : '/mute'),
          ),
          TogglePill(
            key: const Key('toggle-camera'),
            label: 'Camera',
            icon: s.cameraOn ? Icons.videocam : Icons.videocam_off,
            selected: s.cameraOn,
            onChanged: (v) => flip(context, {
              'camera': v ? 'on' : 'OFF',
            }, v ? '/camera on' : '/camera off'),
          ),
          TogglePill(
            key: const Key('toggle-estop'),
            label: 'Emergency stop',
            icon: Icons.front_hand,
            selected: s.estop,
            danger: true,
            onChanged: (v) {
              if (v) {
                unawaited(s.drive(0, 0));
              }
              flip(context, {
                'mode': v ? 'E-STOP' : 'PAUSED',
              }, v ? '/estop' : '/clear');
            },
          ),
        ],
      ],
    );
  }
}

// =====================================================================================================================
class DriveTab extends StatefulWidget {
  const DriveTab({super.key});

  @override
  State<DriveTab> createState() => _DriveTabState();
}

class _DriveTabState extends State<DriveTab> {
  double _x = 0, _y = 0;
  bool _slow = false;
  Timer? _timer;
  final Set<LogicalKeyboardKey> _keys = {};
  final _focus = FocusNode();
  AppState? _appState;
  bool _moving = false; // the last thing we told Bob was to move
  bool _drove = false; // this tab has sent a move since the last explicit stop
  int _stickEpoch = 0; // bumping it rebuilds the stick back at the centre

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    // Keep this while the element is active; Provider lookups are not allowed
    // from dispose.
    _appState = context.read<AppState>();
  }

  @override
  void dispose() {
    _stopDriving();
    _focus.dispose();
    super.dispose();
  }

  /// Stop locally first, so this tab's own timer cannot send another move after the stop. (A move request already on
  /// its way can still arrive late, which is why an explicit stop is sent again even after the stick was released;
  /// Bob's emergency stop is what guarantees the wheels stay off.) Bob is only told when this tab has driven, so
  /// leaving a tab that never drove does not interrupt someone else's manual drive. Redraw only from an event
  /// handler, never from dispose or the focus machinery.
  void _stopDriving({bool redraw = false}) {
    _x = 0;
    _y = 0;
    _keys.clear();
    _timer?.cancel();
    _timer = null;
    final was = _drove;
    _moving = false;
    _drove = false;
    final state = _appState;
    if (was && state != null) unawaited(state.drive(0, 0));
    if (redraw && mounted) setState(() => _stickEpoch++);
  }

  void _setStick(double x, double y) {
    _x = x;
    _y = y;
    _drive();
  }

  void _drive() {
    final s = context.read<AppState>();
    final (l, r) = mixWheels(_x, _y, scale: _slow ? 0.5 : 1.0);
    if (l == 0 && r == 0) {
      _timer?.cancel();
      _timer = null;
      if (_moving) s.drive(0, 0);
      _moving = false;
      return;
    }
    _moving = true;
    _drove = true;
    s.drive(l, r);
    _timer ??= Timer.periodic(const Duration(milliseconds: 250), (_) {
      final (l2, r2) = mixWheels(_x, _y, scale: _slow ? 0.5 : 1.0);
      s.drive(l2, r2);
    });
  }

  KeyEventResult _onKey(FocusNode node, KeyEvent event) {
    if (event is KeyRepeatEvent) return KeyEventResult.handled;
    final k = event.logicalKey;
    if (event is KeyDownEvent && k == LogicalKeyboardKey.space) {
      final s = context.read<AppState>();
      _stopDriving(redraw: true);
      unawaited(s.send('/estop'));
      return KeyEventResult.handled;
    }
    final driving = <LogicalKeyboardKey>{
      LogicalKeyboardKey.keyW,
      LogicalKeyboardKey.arrowUp,
      LogicalKeyboardKey.keyS,
      LogicalKeyboardKey.arrowDown,
      LogicalKeyboardKey.keyA,
      LogicalKeyboardKey.arrowLeft,
      LogicalKeyboardKey.keyD,
      LogicalKeyboardKey.arrowRight,
    };
    if (!driving.contains(k)) return KeyEventResult.ignored;
    if (event is KeyDownEvent) {
      _keys.add(k);
    } else if (event is KeyUpEvent) {
      _keys.remove(k);
    }
    final up =
        _keys.contains(LogicalKeyboardKey.keyW) ||
        _keys.contains(LogicalKeyboardKey.arrowUp);
    final down =
        _keys.contains(LogicalKeyboardKey.keyS) ||
        _keys.contains(LogicalKeyboardKey.arrowDown);
    final left =
        _keys.contains(LogicalKeyboardKey.keyA) ||
        _keys.contains(LogicalKeyboardKey.arrowLeft);
    final right =
        _keys.contains(LogicalKeyboardKey.keyD) ||
        _keys.contains(LogicalKeyboardKey.arrowRight);
    _setStick(
      (right ? 1.0 : 0.0) - (left ? 1.0 : 0.0),
      (up ? 1.0 : 0.0) - (down ? 1.0 : 0.0),
    );
    return KeyEventResult.handled;
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final client = s.client;
    final desktop = Platform.isMacOS || Platform.isWindows || Platform.isLinux;
    return Focus(
      focusNode: _focus,
      autofocus: true,
      onKeyEvent: _onKey,
      onFocusChange: (hasFocus) {
        // Keys held down can't be released once the window loses the keyboard. The stick is a gesture and is
        // unaffected by focus, so tapping another control mid-drag must not stop it.
        if (!hasFocus && _keys.isNotEmpty) _stopDriving();
      },
      child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, _bottomRoom),
        children: [
          if (client != null) MjpegView(key: ValueKey(client), client: client),
          const SizedBox(height: 12),
          Center(
            child: Joystick(key: ValueKey(_stickEpoch), onChanged: _setStick),
          ),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Text('Slow'),
              Switch(value: _slow, onChanged: (v) => setState(() => _slow = v)),
            ],
          ),
          Center(
            child: Text(
              desktop
                  ? 'Drag the stick, or use W A S D / arrow keys. Space is the emergency stop.'
                  : 'Drag the stick to drive. He stops when you let go.',
              style: TextStyle(
                color: Theme.of(context).colorScheme.onSurfaceVariant,
                fontSize: 12,
              ),
              textAlign: TextAlign.center,
            ),
          ),
          const SizedBox(height: 12),
          const ControlToggles(),
        ],
      ),
    );
  }
}

// =====================================================================================================================
class StatusTab extends StatelessWidget {
  const StatusTab({super.key});

  @override
  Widget build(BuildContext context) {
    final st = context.watch<AppState>().status;
    if (st.isEmpty) return const Center(child: Text('No status yet'));
    final usage = (st['usage'] as Map?) ?? const {};
    final vitals = (st['vitals'] as Map?) ?? const {};
    final events = ((st['events'] as List?) ?? const [])
        .whereType<Map>()
        .toList();
    final throttled = statusNumber(vitals['throttled'])?.toInt() ?? 0;
    final scheme = Theme.of(context).colorScheme;
    String money(Object? v) => v is num ? '\$${v.toStringAsFixed(2)}' : '-';

    Widget card(String title, List<Widget> children) => Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 8),
            ...children,
          ],
        ),
      ),
    );

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, _bottomRoom),
      children: [
        card('Bob', [
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              StatChip('AI ${st['thinking'] == true ? 'thinking' : 'idle'}'),
              StatChip(
                'camera ${st['camera']}',
                color: st['camera'] == 'OFF' ? scheme.tertiary : null,
              ),
              StatChip('mic ${st['mic']}'),
              StatChip(st['muted'] == true ? 'audio MUTED' : 'audio on'),
              StatChip('speed cap ${st['cap']}'),
              if (st['sleep'] == true)
                StatChip('sleeping', color: Colors.indigo),
              if (st['follow'] == true)
                const StatChip('following', color: Colors.green),
              if ((st['radio'] ?? '').toString().isNotEmpty)
                StatChip('radio ${st['radio']}'),
              if (statusNumber(st['dist']) case final dist?)
                StatChip(
                  '${dist.round()} cm ahead',
                  color: dist < 20 ? scheme.error : null,
                ),
              if (st['room'] != null) StatChip('in the ${st['room']}'),
              StatChip('${st['model']} / ${st['effort']}'),
            ],
          ),
        ]),
        card('What Claude has cost', [
          Text('This run: ${money(st['cost'])}'),
          Text('Today: ${money(usage['today'])}'),
          Text(
            'All time: ${money(usage['all'])}${usage['since'] != null ? '  (since ${usage['since']})' : ''}',
          ),
          const SizedBox(height: 4),
          Text(
            'An estimate from Bob\'s own calls.',
            style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant),
          ),
        ]),
        card('The Pi', [
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              if (statusNumber(vitals['temp_c']) case final temp?)
                StatChip(
                  '${temp.round()} °C',
                  color: temp >= 80
                      ? scheme.error
                      : temp >= 70
                      ? scheme.tertiary
                      : null,
                ),
              if (statusNumber(vitals['load']) case final load?)
                StatChip('load ${load.toStringAsFixed(1)}'),
              if (statusNumber(vitals['mem_mb']) case final mem?)
                StatChip('${mem.round()} MB free'),
              if (statusNumber(vitals['disk_gb']) case final disk?)
                StatChip('${disk.toStringAsFixed(1)} GB disk'),
              if (throttled & 5 != 0)
                StatChip('power or heat limit', color: scheme.error),
              if (vitals.isEmpty) const Text('No readings'),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            'Bob ${st['version']}',
            style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant),
          ),
        ]),
        if (events.isNotEmpty)
          card('Recent events', [
            for (final e in events.reversed)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 2),
                child: Text(
                  '${eventClock(e['t'], seconds: true)}  ${e['kind']}  ${e['text']}',
                  style: const TextStyle(fontFamily: 'monospace', fontSize: 11),
                ),
              ),
          ]),
      ],
    );
  }
}

/// A finite number from the status JSON (a number or a numeric string), or null.
num? statusNumber(Object? value) {
  final n = value is num ? value : num.tryParse(value?.toString() ?? '');
  return n != null && n.isFinite ? n : null;
}

// =====================================================================================================================
class ChatTab extends StatefulWidget {
  const ChatTab({super.key});

  @override
  State<ChatTab> createState() => _ChatTabState();
}

class _ChatTabState extends State<ChatTab> {
  final _text = TextEditingController();
  final _scroll = ScrollController();

  @override
  void dispose() {
    _text.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final v = _text.text.trim();
    if (v.isEmpty) return;
    _text.clear();
    await runCommand(context, v.startsWith('/') ? v : '/ask $v');
  }

  Color _color(BuildContext context, String level, String tag) {
    final scheme = Theme.of(context).colorScheme;
    if (level == 'ERROR') return scheme.error;
    if (level == 'WARNING') return scheme.tertiary;
    if (tag == 'BOB' || tag == 'SAY') return scheme.primary;
    if (tag == 'HEARD' || tag == 'YOU') return Colors.purple;
    if (tag == 'RADIO') return Colors.green;
    return scheme.onSurface;
  }

  @override
  Widget build(BuildContext context) {
    final lines =
        ((context.watch<AppState>().status['log'] as List?) ?? const [])
            .cast<Map>();
    return Column(
      children: [
        Expanded(
          child: Card(
            margin: const EdgeInsets.fromLTRB(16, 4, 16, 4),
            child: ListView.builder(
              controller: _scroll,
              reverse: true,
              padding: const EdgeInsets.fromLTRB(20, 16, 20, 12),
              itemCount: lines.length,
              itemBuilder: (c, i) {
                final row = lines[lines.length - 1 - i];
                return Padding(
                  padding: const EdgeInsets.symmetric(vertical: 1),
                  child: Text(
                    row['m'].toString(),
                    style: TextStyle(
                      fontFamily: 'monospace',
                      fontSize: 12,
                      color: _color(c, '${row['l']}', '${row['t']}'),
                    ),
                  ),
                );
              },
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, _bottomRoom),
          child: Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _text,
                  onSubmitted: (_) => _send(),
                  decoration: const InputDecoration(
                    hintText: 'Say something to Bob, or a /command',
                  ),
                ),
              ),
              const SizedBox(width: 8),
              IconButton.filled(onPressed: _send, icon: const Icon(Icons.send)),
            ],
          ),
        ),
      ],
    );
  }
}

// =====================================================================================================================
class MoreTab extends StatefulWidget {
  const MoreTab({super.key});

  @override
  State<MoreTab> createState() => _MoreTabState();
}

class _MoreTabState extends State<MoreTab> {
  String? _room;

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final rooms = s.rooms;
    final room = rooms.contains(_room)
        ? _room
        : (rooms.isEmpty ? null : rooms.first);
    Widget cmd(String label, String text, {IconData? icon}) =>
        FilledButton.tonalIcon(
          onPressed: () => runCommand(context, text),
          icon: Icon(icon ?? Icons.bolt),
          label: Text(label),
        );

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, _bottomRoom),
      children: [
        Text('Controls', style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 8),
        const ControlToggles(all: true),
        const SizedBox(height: 12),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            cmd('Check everything', '/check', icon: Icons.health_and_safety),
            cmd('Cost', '/usage', icon: Icons.attach_money),
          ],
        ),
        if (rooms.isNotEmpty) ...[
          const SizedBox(height: 20),
          Text('Go to a room', style: Theme.of(context).textTheme.titleSmall),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: DropdownButtonFormField<String>(
                  initialValue: room,
                  items: [
                    for (final r in rooms)
                      DropdownMenuItem(value: r, child: Text(r)),
                  ],
                  onChanged: (v) => setState(() => _room = v),
                  decoration: const InputDecoration(),
                ),
              ),
              const SizedBox(width: 8),
              FilledButton.icon(
                key: const Key('go-toggle'),
                onPressed: s.going
                    ? () => flip(context, {'going': false}, '/goto stop')
                    : room == null
                    ? null
                    : () => flip(context, {'going': true}, '/goto $room'),
                icon: Icon(s.going ? Icons.stop : Icons.play_arrow),
                label: Text(s.going ? 'Stop' : 'Go'),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            'He follows the room\'s tag, slowly, and stops if anything is in the way.',
            style: TextStyle(
              fontSize: 12,
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
          ),
        ],
        if (s.hasMusic) ...[
          const SizedBox(height: 20),
          Text(
            'Music  ${s.status['music'] ?? ''}',
            style: Theme.of(context).textTheme.titleSmall,
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            children: [
              IconButton.filledTonal(
                onPressed: () => runCommand(context, '/music prev'),
                icon: const Icon(Icons.skip_previous),
              ),
              IconButton.filledTonal(
                onPressed: () => runCommand(context, '/music play'),
                icon: const Icon(Icons.play_arrow),
              ),
              IconButton.filledTonal(
                onPressed: () => runCommand(context, '/music pause'),
                icon: const Icon(Icons.pause),
              ),
              IconButton.filledTonal(
                onPressed: () => runCommand(context, '/music next'),
                icon: const Icon(Icons.skip_next),
              ),
              IconButton.filledTonal(
                onPressed: () => runCommand(context, '/music vol down'),
                icon: const Icon(Icons.volume_down),
              ),
              IconButton.filledTonal(
                onPressed: () => runCommand(context, '/music vol up'),
                icon: const Icon(Icons.volume_up),
              ),
            ],
          ),
        ],
        const SizedBox(height: 24),
        Text('Appearance', style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 8),
        SegmentedButton<ThemeMode>(
          key: const Key('appearance'),
          showSelectedIcon: false,
          segments: const [
            ButtonSegment(
              value: ThemeMode.system,
              icon: Icon(Icons.brightness_auto),
              label: Text('Auto'),
            ),
            ButtonSegment(
              value: ThemeMode.light,
              icon: Icon(Icons.light_mode),
              label: Text('Light'),
            ),
            ButtonSegment(
              value: ThemeMode.dark,
              icon: Icon(Icons.dark_mode),
              label: Text('Dark'),
            ),
          ],
          selected: {s.themeMode},
          onSelectionChanged: (v) => s.setThemeMode(v.first),
        ),
        const SizedBox(height: 24),
        Text('This device', style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 8),
        ListTile(
          contentPadding: EdgeInsets.zero,
          key: const Key('your-name'),
          leading: const Icon(Icons.person_outline),
          title: Text(s.userName ?? 'Add your name'),
          subtitle: const Text('shown in the welcome on the home page'),
          trailing: const Icon(Icons.edit_outlined),
          onTap: () async {
            final controller = TextEditingController(text: s.userName ?? '');
            final name = await showDialog<String>(
              context: context,
              builder: (c) => AlertDialog(
                title: const Text('Your name'),
                content: TextField(
                  controller: controller,
                  autofocus: true,
                  textCapitalization: TextCapitalization.words,
                  onSubmitted: (v) => Navigator.pop(c, v),
                ),
                actions: [
                  TextButton(
                    onPressed: () => Navigator.pop(c),
                    child: const Text('Cancel'),
                  ),
                  FilledButton(
                    onPressed: () => Navigator.pop(c, controller.text),
                    child: const Text('Save'),
                  ),
                ],
              ),
            );
            if (name != null) await s.setUserName(name);
          },
        ),
        ListTile(
          contentPadding: EdgeInsets.zero,
          title: Text('Paired with ${s.robotName}'),
          subtitle: Text(
            '${s.profile?.host}:${s.profile?.port}\nas "${s.profile?.device}"\ncertificate ${s.profile?.fingerprint.substring(0, 16)}...',
          ),
          isThreeLine: true,
        ),
        OutlinedButton.icon(
          onPressed: () async {
            final ok = await showDialog<bool>(
              context: context,
              builder: (c) => AlertDialog(
                title: const Text('Unpair this device?'),
                content: Text(
                  '${s.robotName} will forget this device and you will need a new code to add it again.',
                ),
                actions: [
                  TextButton(
                    onPressed: () => Navigator.pop(c, false),
                    child: const Text('Cancel'),
                  ),
                  FilledButton(
                    onPressed: () => Navigator.pop(c, true),
                    child: const Text('Unpair'),
                  ),
                ],
              ),
            );
            if (ok == true) await s.forget();
          },
          icon: const Icon(Icons.link_off),
          label: const Text('Unpair this device'),
        ),
      ],
    );
  }
}
