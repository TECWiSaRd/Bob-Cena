import 'package:flutter/material.dart';

import 'theme.dart';

/// The BOB wordmark and the Online / Offline line under it.
class BobHeader extends StatelessWidget {
  const BobHeader({
    super.key,
    required this.online,
    this.problem,
    this.compact = false,
    this.onTitleTap,
  });
  final bool online;
  final String? problem;
  final bool compact;
  final VoidCallback? onTitleTap;

  @override
  Widget build(BuildContext context) {
    final ink = Theme.of(context).colorScheme.onSurface;
    final dot = Container(
      width: compact ? 12 : 20,
      height: compact ? 12 : 20,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: online ? BobColors.green : BobColors.red,
      ),
    );
    final status = Text(
      online ? 'Online' : (problem ?? 'Offline'),
      key: const Key('status-text'),
      style: TextStyle(
        fontSize: compact ? 14 : 30,
        color: ink,
        fontWeight: FontWeight.w400,
      ),
      overflow: TextOverflow.ellipsis,
    );
    final title = GestureDetector(
      onTap: onTitleTap,
      child: Text(
        'BOB',
        key: const Key('wordmark'),
        style: TextStyle(
          fontFamily: BobFonts.title,
          fontSize: compact ? 30 : 64,
          height: 1,
          color: ink,
        ),
      ),
    );
    if (compact) {
      return Row(
        children: [
          title,
          const SizedBox(width: 14),
          dot,
          const SizedBox(width: 8),
          Flexible(child: status),
        ],
      );
    }
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        title,
        const SizedBox(height: 8),
        Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            dot,
            const SizedBox(width: 12),
            Flexible(child: status),
          ],
        ),
      ],
    );
  }
}

/// "Welcome back, Adam." in a thin script with the name in a heavy face. One line of text, so the full stop sits on the same
/// baseline as the name instead of floating beside it.
class Greeting extends StatelessWidget {
  const Greeting({super.key, this.name, this.size = 76});
  final String? name;
  final double size;

  @override
  Widget build(BuildContext context) {
    final ink = Theme.of(context).colorScheme.onSurface;
    final script = TextStyle(
      fontFamily: BobFonts.script,
      fontSize: size,
      height: 1.1,
      color: ink,
    );
    final heavy = TextStyle(
      fontFamily: BobFonts.heavy,
      fontSize: size * 0.62,
      color: ink,
      fontVariations: const [FontVariation('wght', 900)],
    );
    return Text.rich(
      key: const Key('greeting'),
      textAlign: TextAlign.center,
      TextSpan(
        style: script,
        children: [
          TextSpan(text: name == null ? 'Welcome back' : 'Welcome back, '),
          if (name != null) TextSpan(text: name, style: heavy),
          TextSpan(
            text: '.',
            style: script,
          ), // the script's own small full stop, on the same baseline as the name
        ],
      ),
    );
  }
}

/// A big rounded white card with a small label, a big value and a line of detail.
class InfoPill extends StatelessWidget {
  const InfoPill({
    super.key,
    required this.label,
    required this.value,
    this.detail,
    this.onTap,
    this.height = 150,
  });
  final String label;
  final String value;
  final String? detail;
  final VoidCallback? onTap;
  final double height;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final small =
        height <
        130; // phone-sized card: a smaller number and one line of detail
    return Material(
      color: scheme.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(height / 2),
      ),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: SizedBox(
          height: height,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 28),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(
                  label,
                  style: TextStyle(
                    fontSize: 13,
                    letterSpacing: 1.2,
                    color: scheme.onSurface.withValues(alpha: 0.55),
                  ),
                ),
                const SizedBox(height: 4),
                FittedBox(
                  fit: BoxFit.scaleDown,
                  child: Text(
                    value,
                    style: TextStyle(
                      fontFamily: BobFonts.heavy,
                      fontSize: small ? 30 : 36,
                      color: scheme.onSurface,
                      fontVariations: const [FontVariation('wght', 800)],
                    ),
                  ),
                ),
                if (detail != null) ...[
                  const SizedBox(height: 2),
                  Text(
                    detail!,
                    textAlign: TextAlign.center,
                    maxLines: small ? 1 : 2,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      fontSize: 14,
                      color: scheme.onSurface.withValues(alpha: 0.7),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class NavItem {
  const NavItem(this.id, this.label, this.icon);
  final String id;
  final String label;
  final IconData icon;
}

/// The icon-only navigation bar that fades in from the page colour to white (or the dark surface).
class BobNavBar extends StatelessWidget {
  const BobNavBar({
    super.key,
    required this.items,
    required this.selected,
    required this.onSelect,
  });
  final List<NavItem> items;
  final int? selected; // null = on the home page: nothing is highlighted
  final void Function(int index) onSelect;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final bg = Theme.of(context).scaffoldBackgroundColor;
    return Container(
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [bg.withValues(alpha: 0), scheme.surface, scheme.surface],
          stops: const [0, 0.55, 1],
        ),
      ),
      padding: EdgeInsets.fromLTRB(
        16,
        28,
        16,
        12 + MediaQuery.of(context).padding.bottom,
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceEvenly,
        children: [
          for (var i = 0; i < items.length; i++)
            Tooltip(
              message: items[i].label,
              child: Semantics(
                button: true,
                selected: selected == i,
                label: items[i].label,
                child: InkResponse(
                  key: Key('nav-${items[i].id}'),
                  onTap: () => onSelect(i),
                  radius: 36,
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Icon(
                      items[i].icon,
                      size: 38,
                      color: selected == i ? scheme.primary : scheme.onSurface,
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}
