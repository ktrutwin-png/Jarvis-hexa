from __future__ import annotations

import pytest

from heksa.order_lifecycle import ExecutionLimits, OrderLifecycle


def proposal(
    *,
    pair: str = "XRP/EUR",
    position_eur: float = 5.0,
    confidence: float = 72.0,
    entry: float = 1.0,
) -> dict:
    return {
        "pair": pair,
        "api_pair": pair.replace("/", ""),
        "status": "PROPOSAL",
        "position_eur": position_eur,
        "requires_user_approval": True,
        "signal": {
            "signal": "BUY_CANDIDATE",
            "confidence": confidence,
            "last_price": entry,
            "stop_loss": entry * 0.995,
            "take_profit": entry * 1.01,
        },
        "execution": {
            "slippage_bps": 3.0,
            "executable": True,
        },
        "live_order_submitted": False,
    }


def test_manual_approval_and_simulation_are_persistent(tmp_path):
    lifecycle = OrderLifecycle(tmp_path / "orders.sqlite3")

    validated = lifecycle.create_from_proposal(proposal())
    assert validated["state"] == "VALIDATED"
    assert validated["client_order_id"].startswith("nx")

    approved = lifecycle.approve(validated["id"])
    assert approved["state"] == "APPROVED"
    assert approved["approved_at"]

    simulated = lifecycle.simulate(validated["id"])
    assert simulated["state"] == "SIMULATED"
    assert simulated["fill_price"] > 1.0
    assert simulated["fee_eur"] > 0
    assert simulated["result"]["live_order_submitted"] is False

    reopened = OrderLifecycle(tmp_path / "orders.sqlite3")
    stored = reopened.get(validated["id"])
    assert stored is not None
    assert stored["state"] == "SIMULATED"
    assert reopened.summary()["simulations_today"] == 1


def test_same_signal_is_idempotent_for_the_day(tmp_path):
    lifecycle = OrderLifecycle(tmp_path / "orders.sqlite3")
    first = lifecycle.create_from_proposal(proposal())
    second = lifecycle.create_from_proposal(proposal())

    assert first["id"] == second["id"]
    assert lifecycle.summary()["total_orders"] == 1


def test_emergency_stop_blocks_pending_and_new_orders(tmp_path):
    lifecycle = OrderLifecycle(tmp_path / "orders.sqlite3")
    order = lifecycle.create_from_proposal(proposal())

    result = lifecycle.set_emergency_stop(True)
    assert result["emergency_stop"] is True
    assert result["blocked_pending_orders"] == 1
    assert lifecycle.get(order["id"])["state"] == "BLOCKED"

    with pytest.raises(PermissionError, match="emergency stop"):
        lifecycle.create_from_proposal(proposal(pair="ETH/EUR", entry=2000.0))

    lifecycle.set_emergency_stop(False)
    replacement = lifecycle.create_from_proposal(
        proposal(pair="ETH/EUR", entry=2000.0)
    )
    assert replacement["state"] == "VALIDATED"


def test_hard_pending_exposure_limit_cannot_be_bypassed(tmp_path):
    lifecycle = OrderLifecycle(
        tmp_path / "orders.sqlite3",
        limits=ExecutionLimits(
            max_position_eur=10.0,
            max_pending_orders=3,
            max_pending_exposure_eur=10.0,
        ),
    )
    lifecycle.create_from_proposal(proposal(position_eur=6.0))

    with pytest.raises(PermissionError, match="exposure"):
        lifecycle.create_from_proposal(
            proposal(pair="ETH/EUR", position_eur=6.0, entry=2000.0)
        )


def test_daily_loss_circuit_breaker_blocks_new_orders(tmp_path):
    lifecycle = OrderLifecycle(
        tmp_path / "orders.sqlite3",
        limits=ExecutionLimits(max_daily_loss_eur=3.0),
    )
    assert lifecycle.record_realized_pnl(-3.0) == -3.0

    with pytest.raises(PermissionError, match="daily loss"):
        lifecycle.create_from_proposal(proposal())


def test_non_actionable_or_weak_signal_is_rejected(tmp_path):
    lifecycle = OrderLifecycle(tmp_path / "orders.sqlite3")
    weak = proposal(confidence=10.0)

    with pytest.raises(ValueError, match="confidence"):
        lifecycle.create_from_proposal(weak)

    waiting = proposal()
    waiting["status"] = "WAIT"
    with pytest.raises(ValueError, match="PROPOSAL"):
        lifecycle.create_from_proposal(waiting)
