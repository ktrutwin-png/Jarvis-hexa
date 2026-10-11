import unittest

from heksa.risk import validate_risk


class RiskTests(unittest.TestCase):
    def test_accepts_bounded_proposal(self):
        validate_risk(10.0, 100.0, 99.0, 102.0)

    def test_rejects_position_over_limit(self):
        with self.assertRaises(ValueError):
            validate_risk(10.01, 100.0, 99.0, 102.0)

    def test_rejects_excessive_stop(self):
        with self.assertRaises(ValueError):
            validate_risk(10.0, 100.0, 98.0, 104.0)

    def test_rejects_weak_reward_risk(self):
        with self.assertRaises(ValueError):
            validate_risk(10.0, 100.0, 99.0, 101.0)


if __name__ == "__main__":
    unittest.main()
