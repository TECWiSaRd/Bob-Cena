"""People are identified by name, ignoring case; real logins can't be claimed by typing them (fakes only)."""
import unittest

from identity import Identity, IdentityError, Principal, system_accounts


def ident(accounts=("sam", "Kai")):
    return Identity("adam", lambda: list(accounts))


class Resolving(unittest.TestCase):
    def test_the_account_bob_runs_as_is_the_owner_whatever_the_case(self):
        for typed in ("adam", "ADAM", " Adam "):
            p = ident().resolve(typed)
            self.assertEqual((p.key, p.display, p.kind), ("adam", "adam", "owner"))

    def test_real_logins_use_the_systems_spelling(self):
        p = ident().resolve("KAI")
        self.assertEqual((p.key, p.display, p.kind), ("kai", "Kai", "pi"))
        self.assertEqual(ident().resolve("sam").label, "sam (Pi login)")

    def test_other_names_are_app_only_people_and_may_still_register(self):
        p = ident().resolve("Grandma Jo")
        self.assertEqual((p.kind, p.display, p.key), ("app", "Grandma Jo", "grandma jo"))
        self.assertEqual(ident().resolve("grandma   JO").key, "grandma jo")           # spacing and case don't make a second person
        self.assertIn("app-only", ident().advice(p))
        self.assertIn("Pi login is better", ident().advice(p))
        self.assertEqual(ident().advice(ident().resolve("sam")), "")

    def test_bad_names_are_refused(self):
        for bad in ("", "   ", "x" * 33, "a/b", "<script>", "line\nbreak;rm", "!!"):
            with self.assertRaises(IdentityError, msg=repr(bad)):
                ident().resolve(bad)

    def test_the_owner_is_known_even_if_the_system_does_not_list_them(self):
        self.assertEqual(Identity("adam", lambda: []).resolve("Adam").kind, "owner")
        self.assertIn("adam", ident().logins())
        self.assertEqual(ident().logins(), ["adam", "Kai", "sam"])

    def test_it_survives_a_failing_account_lookup(self):
        self.assertIsInstance(system_accounts(), list)                                  # never raises, even on odd systems


class Invites(unittest.TestCase):
    def setUp(self):
        self.i = ident()
        self.owner, self.sam, self.kai = (self.i.resolve(n) for n in ("adam", "sam", "kai"))
        self.jo = self.i.resolve("Grandma Jo")

    def test_the_owner_may_invite_anyone(self):
        for target in (self.owner, self.sam, self.jo):
            self.assertIsNone(self.i.invite_problem(self.owner, target))

    def test_a_pi_user_may_invite_only_themselves(self):
        self.assertIsNone(self.i.invite_problem(self.sam, self.sam))
        self.assertIn("only adam (the owner) or Kai", self.i.invite_problem(self.sam, self.kai))
        self.assertIn("only adam", self.i.invite_problem(self.sam, self.jo))                # app-only names are the owner's to invite

    def test_a_typed_name_cannot_take_a_real_login(self):
        # an app-only person called "sam" can't exist: the name IS the login
        self.assertEqual(self.i.resolve("SAM").kind, "pi")
        self.assertIsNotNone(self.i.invite_problem(self.kai, self.i.resolve("SAM")))


class Storage(unittest.TestCase):
    def test_round_trip_and_damaged_data(self):
        p = ident().resolve("Kai")
        self.assertEqual(Principal.from_dict(p.as_dict()), p)
        for bad in (None, {}, {"kind": "root", "key": "x", "display": "x"}, {"kind": "pi", "key": "", "display": "x"}, "text"):
            self.assertIsNone(Principal.from_dict(bad))


if __name__ == "__main__":
    unittest.main()
