from decimal import Decimal

import pytest

from heksa.order_rules import MarketRules
from tests.test_trade_intent import market_rules


def test_exact_tick_and_volume_rounding_never_increase_budget_or_risk():
    rules = MarketRules.from_metadata("XBT/EURC", market_rules())
    order = rules.prepare_buy("10", "100.19999", "99.41", "102.09")
    assert order == {"volume": "0.0999", "price": "100.1", "stop": "99.5",
                     "target": "102", "notional": "9.99999"}
    assert Decimal(order["volume"]) * Decimal(order["price"]) <= Decimal("10")


@pytest.mark.parametrize("change", [
    {"ordermin": "1"}, {"costmin": "11"},
    {"costmin": "9.99"},  # Affordable entry, but planned stop exit is too small.
])
def test_minimums_cannot_be_met_by_silently_increasing_budget(change):
    rules = MarketRules.from_metadata("XBT/EURC", {**market_rules(), **change})
    with pytest.raises(ValueError, match="minimum"):
        rules.prepare_buy("10", "100.19999", "99.41", "102.09")


@pytest.mark.parametrize("change", [
    {"status": "cancel_only"}, {"lot_decimals": True}, {"tick_size": "NaN"},
    {"tick_size": "0"}, {"tick_size": "0.15"}, {"ordermin": None},
    {"lot_multiplier": 10}, {"wsname": "ETH/EURC"},
])
def test_incomplete_or_inconsistent_rules_block_preparation(change):
    with pytest.raises(ValueError):
        MarketRules.from_metadata("XBT/EURC", {**market_rules(), **change})


def test_coarse_tick_that_merges_entry_and_stop_blocks_trade():
    rules = MarketRules.from_metadata("XBT/EURC", {**market_rules(), "tick_size": "1"})
    with pytest.raises(ValueError, match="rounding"):
        rules.prepare_buy("10", "100.1", "99.9", "102")


def test_fresh_pair_lookup_bypasses_cached_metadata(monkeypatch):
    from heksa import kraken_market
    calls = []
    def get(endpoint, params, cache_ttl):
        calls.append(cache_ttl)
        return {"XBTEURC": market_rules()}
    monkeypatch.setattr(kraken_market, "_public_get", get)
    assert kraken_market.fetch_current_pair_rules("XBT/EURC")["status"] == "online"
    assert calls == [0]


def test_unplaceable_top_rank_does_not_hide_next_valid_market(monkeypatch):
    from types import SimpleNamespace
    from heksa import trading_runner
    from heksa.pair_scanner import PairOpportunity
    from tests.test_trade_intent import proposal
    opportunities = []
    for pair, score, minimum in (("XBT/EURC", 10, "1"), ("ETH/EURC", 9, "0.001")):
        api_pair = pair.replace("/", "")
        rules = {**market_rules(), "wsname": pair, "altname": api_pair, "ordermin": minimum}
        opportunities.append(PairOpportunity(pair, api_pair, 100, 100000, 3, 5, 40, 85, score, rules))
    monkeypatch.setattr(trading_runner, "rank_eurc_pairs", lambda **_: opportunities)
    def make_proposal(pair, api_pair, **_):
        item = proposal()
        item.update(pair=pair, api_pair=api_pair)
        item["signal"]["confidence"] = 100
        return item
    monkeypatch.setattr(trading_runner, "build_market_proposal", make_proposal)
    monkeypatch.setattr(trading_runner, "assess_execution", lambda *_, **__: SimpleNamespace(
        executable=True, book_imbalance=0, to_dict=lambda: {"executable": True, "average_price": 100.05}))
    result = trading_runner.build_best_eurc_proposals(limit=1, entry_side="buy")
    assert result["proposals"][0]["pair"] == "ETH/EURC"
    assert result["proposals"][0]["status"] == "PROPOSAL"
