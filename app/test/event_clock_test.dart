import 'package:bob_app/src/app_state.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('eventClock gives the same clock to both lists', () {
    expect(eventClock('2026-10-25 14:03:09'), '14:03');
    expect(eventClock('2026-10-25 14:03:09', seconds: true), '14:03:09');
    expect(eventClock('2026-10-25 14:03'), '14:03');
    expect(eventClock('2026-10-25 14:03', seconds: true), '14:03');
    expect(eventClock('soon'), 'soon');
    expect(eventClock(null), '');
  });
}
