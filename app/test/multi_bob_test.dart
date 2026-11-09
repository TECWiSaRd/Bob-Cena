import 'dart:convert';

import 'package:bob_app/src/app_state.dart';
import 'package:bob_app/src/profile.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

BobProfile bob(String name, String fp, {String host = 'h', String? user}) =>
    BobProfile(
      name: name,
      host: host,
      port: 8443,
      fingerprint: fp * 64,
      token: 't-$name',
      device: 'My Mac',
      user: user,
    );

AppState fresh() => AppState(autoConnect: false);

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('an older single-Bob save is picked up and moved to the list', () async {
    SharedPreferences.setMockInitialValues({
      'bob_profile_v1': jsonEncode(bob('Bob', 'a').toJson()),
    });
    final s = fresh();
    await s.load();
    expect(s.profiles.map((p) => p.name), ['Bob']);
    expect(s.profile!.name, 'Bob');
    await s.setUserName(
      'Adam',
    ); // saving writes the new list and drops the old key
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString('bob_profile_v1'), isNull);
    final again = fresh();
    await again.load();
    expect(again.profile!.user, 'Adam');
  });

  test('pairing a second Bob keeps the first and uses the new one', () async {
    final s = fresh();
    await s.load();
    await s.setProfile(bob('Bob', 'a'));
    s.startAddingBob();
    expect(s.addingBob, isTrue);
    await s.setProfile(bob('Garage Bob', 'b'));
    expect(s.addingBob, isFalse);
    expect(s.profiles.map((p) => p.name), ['Bob', 'Garage Bob']);
    expect(s.profile!.name, 'Garage Bob');
  });

  test(
    'pairing the same Bob again replaces him instead of adding a copy',
    () async {
      final s = fresh();
      await s.load();
      await s.setProfile(bob('Bob', 'a', host: 'old'));
      await s.setProfile(bob('Bob', 'a', host: 'new'));
      expect(s.profiles, hasLength(1));
      expect(s.profile!.host, 'new');
    },
  );

  test(
    'switching changes the Bob in use, clears his status and is remembered',
    () async {
      final s = fresh();
      await s.load();
      await s.setProfile(bob('Bob', 'a'));
      await s.setProfile(bob('Garage Bob', 'b'));
      s.status = {'mode': 'AUTO'};
      await s.switchTo('a' * 64);
      expect(s.robotName, 'Bob');
      expect(s.status, isEmpty);
      await s.switchTo('zzz'); // not one of ours: nothing happens
      expect(s.robotName, 'Bob');
      final again = fresh();
      await again.load();
      expect(again.robotName, 'Bob');
      expect(again.profiles, hasLength(2));
    },
  );

  test(
    'forgetting one Bob falls back to another; forgetting the last shows pairing',
    () async {
      final s = fresh();
      await s.load();
      await s.setProfile(bob('Bob', 'a'));
      await s.setProfile(bob('Garage Bob', 'b'));
      await s.forget(); // Garage Bob
      expect(s.profiles.map((p) => p.name), ['Bob']);
      expect(s.profile!.name, 'Bob');
      await s.forget();
      expect(s.profile, isNull);
      expect(s.profiles, isEmpty);
      final again = fresh();
      await again.load();
      expect(again.profile, isNull);
    },
  );

  test('each Bob keeps his own name for you', () async {
    final s = fresh();
    await s.load();
    await s.setProfile(bob('Bob', 'a'));
    await s.setUserName('Adam');
    await s.setProfile(bob('Garage Bob', 'b'));
    await s.setUserName('Sam');
    await s.switchTo('a' * 64);
    expect(s.userName, 'Adam');
  });
}
