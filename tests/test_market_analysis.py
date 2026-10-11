import unittest

from heksa.market_analysis import analyze_prices


class MarketAnalysisTests(unittest.TestCase):
    def test_rejects_bad_prices(self):
        for bad in (float("nan"), float("inf"), 0, -1):
            with self.subTest(price=bad):
                with self.assertRaises(ValueError):
                    analyze_prices([100] * 21 + [bad])

    def test_rejects_invalid_settings(self):
        for settings in ({"fast_window": 0}, {"fast_window": 21},
                         {"slow_window": 2.5}, {"risk_pct": float("nan")},
                         {"reward_pct": 1}, {"risk_pct": -0.01}):
            with self.subTest(settings=settings):
                with self.assertRaises(ValueError):
                    analyze_prices([100] * 30, **settings)

    def test_uptrend_creates_buy_candidate(self):
        prices = list(range(1, 30))
        result = analyze_prices(prices)
        self.assertEqual(result.signal, "BUY_CANDIDATE")
        self.assertLess(result.stop_loss, result.last_price)
        self.assertGreater(result.take_profit, result.last_price)

    def test_downtrend_creates_sell_candidate(self):
        prices = list(range(30, 1, -1))
        result = analyze_prices(prices)
        self.assertEqual(result.signal, "SELL_CANDIDATE")
        self.assertGreater(result.stop_loss, result.last_price)
        self.assertLess(result.take_profit, result.last_price)

    def test_requires_enough_prices(self):
        with self.assertRaises(ValueError):
            analyze_prices([1, 2, 3])


if __name__ == "__main__":
    unittest.main()
