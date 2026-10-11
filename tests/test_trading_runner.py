import unittest
from unittest.mock import patch

from heksa.trading_runner import build_market_proposal


class TradingRunnerTests(unittest.TestCase):
    @patch("heksa.trading_runner.fetch_close_prices")
    def test_proposal_never_claims_live_submission(self, fetch):
        fetch.return_value = list(range(1, 30))
        proposal = build_market_proposal("XRPEUR")
        self.assertTrue(proposal["requires_user_approval"])
        self.assertFalse(proposal["live_order_submitted"])
        self.assertEqual(proposal["pair"], "XRPEUR")

    @patch("heksa.trading_runner.fetch_close_prices")
    def test_market_data_failure_propagates(self, fetch):
        fetch.side_effect = RuntimeError("market data unavailable")
        with self.assertRaises(RuntimeError):
            build_market_proposal("XRPEUR")


if __name__ == "__main__":
    unittest.main()
