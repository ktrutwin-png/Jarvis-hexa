from datetime import datetime, timedelta, timezone

import pytest

from heksa.risk import validate_risk
from heksa.trade_intent import build_trade_intent, recheck_approved_intent


def proposal():
    now = datetime.now(timezone.utc)
    return {
        "proposal_id": "reviewed-1", "pair": "XBT/EURC", "api_pair": "XBTEURC",
        "status": "PROPOSAL", "requires_user_approval": True,
        "analyzed_at": now.isoformat(), "expires_at": (now + timedelta(seconds=120)).isoformat(),
        "position_eurc": 10, "estimated_round_trip_cost_bps": 85,
        "opportunity": {"taker_fee_bps": 40},
        "signal": {"signal": "BUY_CANDIDATE", "last_price": 100,
                   "stop_loss": 99.5, "take_profit": 102},
        "execution": {"executable": True, "average_price": 100.05},
    }


def recheck(item, fingerprint, **changes):
    now = datetime.now(timezone.utc)
    values = dict(current_ask=100.1, quote_time=now, available_eurc=10.1,
                  estimated_entry_fee_eurc=0.04, estimated_round_trip_cost_eurc=0.085,
                  now=now)
    values.update(changes)
    return recheck_approved_intent(item, fingerprint, **values)


def test_review_contains_automatic_exit_and_new_entry_requires_consent():
    item = proposal()
    intent = build_trade_intent(item)
    assert intent.entry_side == "buy" and intent.exit_side == "sell"
    assert intent.settlement_currency == "EURC"
    assert intent.auto_exit_after_approved_entry
    assert intent.next_entry_requires_new_approval
    assert intent.estimated_target_pnl_eurc > 0
    assert intent.estimated_stop_pnl_eurc < 0
    assert recheck(item, intent.fingerprint) == intent


def test_changed_exit_or_replaced_proposal_requires_new_approval():
    item = proposal()
    fingerprint = build_trade_intent(item).fingerprint
    item["signal"]["take_profit"] = 103
    with pytest.raises(ValueError, match="new approval"):
        recheck(item, fingerprint)
    item["signal"]["take_profit"] = 102
    item["proposal_id"] = "replacement"
    with pytest.raises(ValueError, match="new approval"):
        recheck(item, fingerprint)


@pytest.mark.parametrize("changes", [
    {"current_ask": 101}, {"current_ask": 99},
    {"current_ask": float("nan")}, {"available_eurc": 10},
    {"available_eurc": float("inf")}, {"estimated_entry_fee_eurc": 0.05},
    {"estimated_round_trip_cost_eurc": 0.09},
    {"estimated_round_trip_cost_eurc": 0.04},
])
def test_preflight_blocks_invalid_price_balance_and_changed_costs(changes):
    item = proposal()
    with pytest.raises(ValueError):
        recheck(item, build_trade_intent(item).fingerprint, **changes)


def test_expiry_and_stale_quote_block_preflight():
    item = proposal()
    fingerprint = build_trade_intent(item).fingerprint
    with pytest.raises(ValueError, match="stale"):
        recheck(item, fingerprint, quote_time=datetime.now(timezone.utc) - timedelta(seconds=11))
    later = datetime.fromisoformat(item["expires_at"]) + timedelta(seconds=1)
    with pytest.raises(ValueError, match="expired"):
        recheck(item, fingerprint, now=later)


@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, 0])
def test_nonfinite_or_nonpositive_risk_values_never_pass(index, bad):
    values = [10, 100, 99.5, 102]
    values[index] = bad
    with pytest.raises(ValueError):
        validate_risk(*values)


def test_sell_signal_is_not_a_fresh_eurc_funded_entry():
    item = proposal()
    item["signal"]["signal"] = "SELL_CANDIDATE"
    with pytest.raises(ValueError, match="buy signal"):
        build_trade_intent(item)


def test_missing_manual_approval_requirement_is_not_actionable():
    item = proposal()
    del item["requires_user_approval"]
    with pytest.raises(ValueError, match="not actionable"):
        build_trade_intent(item)


def test_entry_cap_is_tightened_to_respect_original_risk_limits():
    item = proposal()
    item["signal"].update(stop_loss=99.4, take_profit=101.2)
    intent = build_trade_intent(item)
    assert intent.entry_limit_eurc < 100.2
    validate_risk(10, intent.entry_limit_eurc, 99.4, 101.2)
