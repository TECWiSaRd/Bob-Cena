import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'app_state.dart';

/// The Bluetooth card at the top of the Drive tab: connect to Bob when there is no Wi-Fi (no camera over Bluetooth).
class BluetoothPanel extends StatelessWidget {
  const BluetoothPanel({super.key});

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    if (s.profile == null) return const SizedBox.shrink();
    final scheme = Theme.of(context).colorScheme;
    final link = s.ble;
    final linkProblem = link != null && !link.ready ? link.problem : null;
    final problem = s.bleProblem ?? linkProblem;

    final String title;
    final String detail;
    Widget? action;
    if (s.usingBluetooth) {
      title = 'Driving over Bluetooth';
      detail =
          'No camera on this link: watch Bob instead. The emergency stop works.';
      action = OutlinedButton(
        key: const ValueKey('ble-disconnect'),
        onPressed: s.bleBusy ? null : s.disconnectBluetooth,
        child: const Text('Disconnect'),
      );
    } else if (s.bleAvailable) {
      title = 'Bluetooth';
      detail = 'For when there is no Wi-Fi. Stay within a few metres of Bob.';
      action = FilledButton(
        key: const ValueKey('ble-connect'),
        onPressed: s.bleBusy ? null : s.connectBluetooth,
        child: s.bleBusy
            ? const SizedBox(
                width: 18,
                height: 18,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            : const Text('Connect'),
      );
    } else {
      title = 'Bluetooth';
      detail =
          'One-time setup: this needs Wi-Fi once (at home) to get this device its Bluetooth key.';
      action = OutlinedButton(
        key: const ValueKey('ble-get-key'),
        onPressed: (s.bleBusy || !s.online) ? null : s.prepareBluetooth,
        child: const Text('Get key'),
      );
    }

    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  s.usingBluetooth
                      ? Icons.bluetooth_connected
                      : Icons.bluetooth,
                  color: s.usingBluetooth ? Colors.blue : null,
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        title,
                        style: Theme.of(context).textTheme.titleSmall,
                      ),
                      Text(
                        detail,
                        style: TextStyle(
                          color: scheme.onSurfaceVariant,
                          fontSize: 12,
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 8),
                action,
              ],
            ),
            if (problem != null)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(
                  problem,
                  key: const ValueKey('ble-problem'),
                  style: TextStyle(color: scheme.error, fontSize: 12),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
