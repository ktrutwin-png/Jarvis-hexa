import unittest

from heksa.risk import RiskLimits, validate_risk


class RiskTests(unittest.TestCase):
    def test_rejects_nonfinite_and_nonpositive_values_in_every_input(self):
        for index in range(4):
            for invalid in (float("nan"), float("inf"), -float("inf"), 0, -1, True):
                values = [10.0, 100.0, 99.0, 102.0]
                values[index] = invalid
                with self.subTest(index=index, invalid=invalid):
                    with self.assertRaises(ValueError):
                        validate_risk(*values)

    def test_rejects_invalid_configured_limits(self):
        for limits in (RiskLimits(max_position_eur=float("nan")),
                       RiskLimits(max_stop_pct=float("inf")),
                       RiskLimits(min_reward_risk=0), RiskLimits(max_stop_pct=1)):
            with self.subTest(limits=limits):
                with self.assertRaises(ValueError):
                    validate_risk(10, 100, 99, 102, limits)

    def test_trade_direction_must_match_levels(self):
        validate_risk(10, 100, 99, 102, side="buy")
        validate_risk(10, 100, 101, 98, side="sell")
        for stop, target, side in ((99, 102, "sell"), (101, 98, "buy"),
                                   (99, 98, None), (101, 102, None),
                                   (99, 102, "unknown")):
            with self.subTest(stop=stop, target=target, side=side):
                with self.assertRaises(ValueError):
                    validate_risk(10, 100, stop, target, side=side)

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
