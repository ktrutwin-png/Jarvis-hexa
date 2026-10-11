import unittest
from unittest.mock import patch

from heksa.indicator_engine import RegimeSignal
from heksa.trading_runner import build_market_proposal


def neutral_test_regime() -> RegimeSignal:
    """Return a deterministic neutral regime for unit tests."""
    return RegimeSignal(
        available=False,
        source="test",
        regime="unknown",
        adx=None,
        plus_di=None,
        minus_di=None,
        rsi=None,
        atr_pct=None,
        direction_ok=True,
        volatility_ok=True,
        score_multiplier=1.0,
    )


class TradingRunnerTests(unittest.TestCase):
    def test_proposal_never_claims_live_submission(self):
        # Keep this unit test deterministic and offline. Live Kraken regime data
        # must not decide whether the mocked price series becomes a proposal.
        with (
            patch(
                "heksa.trading_runner.fetch_close_prices",
                return_value=list(range(1, 30)),
            ),
            patch("heksa.trading_runner.fetch_ohlcv", return_value=[]),
            patch(
                "heksa.trading_runner.analyze_regime",
                return_value=neutral_test_regime(),
            ),
        ):
            proposal = build_market_proposal("XRPEUR")

        self.assertEqual(proposal["status"], "PROPOSAL")
        self.assertTrue(proposal["requires_user_approval"])
        self.assertFalse(proposal["live_order_submitted"])
        self.assertEqual(proposal["pair"], "XRPEUR")

    @patch("heksa.trading_runner.fetch_close_prices")
    def test_wait_signal_does_not_request_approval(self, fetch):
        fetch.return_value = [1.0] * 30

        result = build_market_proposal("XRPEUR")

        self.assertEqual(result["status"], "WAIT")
        self.assertFalse(result["requires_user_approval"])
        self.assertFalse(result["live_order_submitted"])

    @patch("heksa.trading_runner.fetch_close_prices")
    def test_market_data_failure_propagates(self, fetch):
        fetch.side_effect = RuntimeError("market data unavailable")
        with self.assertRaises(RuntimeError):
            build_market_proposal("XRPEUR")


if __name__ == "__main__":
    unittest.main()
