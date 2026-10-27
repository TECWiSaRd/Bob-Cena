"""Bob has no way to judge distance from a picture, so his instructions tell him not to say how far away people are."""
import unittest

import brain


class DistancePrompt(unittest.TestCase):
    def test_he_is_told_not_to_guess_distances(self):
        text = " ".join(brain.SYSTEM_PROMPT.split())
        self.assertIn("never say how far away something is", text)
        self.assertIn("right next to you", text)

    def test_the_sensor_still_counts_as_a_real_reading(self):
        text = " ".join(brain.SYSTEM_PROMPT.split())
        self.assertIn('"Distance sensor" line', text)
        self.assertIn("unless a distance reading", text)


if __name__ == "__main__":
    unittest.main()
