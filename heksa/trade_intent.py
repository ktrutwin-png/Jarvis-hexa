"""Immutable review terms for a spot EURC buy and its eventual automatic exit.

This module prepares and rechecks consent bounds. It does not place an order.
An executor must additionally reconcile holdings/fills and confirm exchange-side
protection; a passing preflight is not itself evidence of an executed trade.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from typing import Mapping

from .market_config import base_symbol, require_eurc_pair
from .risk import RiskLimits, validate_risk


def _positive(value, label: str, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label}: invalid number")
    try:
        number = float(value)
    except (ValueError, TypeError):
        raise ValueError(f"{label}: invalid number") from None
    if not math.isfinite(number) or number < 0 or (not allow_zero and number == 0):
        raise ValueError(f"{label}: invalid number")
    return number


def _timestamp(value, label: str) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise ValueError(f"{label}: invalid timestamp") from None
    if result.tzinfo is None:
        raise ValueError(f"{label}: timezone required")
    return result.astimezone(timezone.utc)


@dataclass(frozen=True)
class TradeIntent:
    proposal_id: str
    pair: str
    api_pair: str
    analyzed_at: str
    expires_at: str
    position_eurc: float
    reference_price_eurc: float
    entry_limit_eurc: float
    stop_trigger_eurc: float
    take_profit_eurc: float
    entry_fee_allowance_eurc: float
    estimated_round_trip_cost_eurc: float
    estimated_target_pnl_eurc: float
    estimated_stop_pnl_eurc: float
    entry_side: str = "buy"
    exit_side: str = "sell"
    settlement_currency: str = "EURC"
    auto_exit_after_approved_entry: bool = True
    next_entry_requires_new_approval: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_trade_intent(proposal: Mapping, *, now: datetime | None = None) -> TradeIntent:
    now = now or datetime.now(timezone.utc)
    if proposal.get("status") != "PROPOSAL" or proposal.get("requires_user_approval") is not True:
        raise ValueError("proposal is not actionable")
    identifier = proposal.get("proposal_id")
    if not isinstance(identifier, str) or not identifier.strip():
        raise ValueError("proposal identity is missing")
    pair = require_eurc_pair(str(proposal.get("pair") or ""))
    api_pair = require_eurc_pair(str(proposal.get("api_pair") or pair))
    if base_symbol(pair) != base_symbol(api_pair):
        raise ValueError("displayed pair does not match order pair")
    signal = proposal.get("signal") or {}
    if signal.get("signal") != "BUY_CANDIDATE":
        raise ValueError("EURC-funded spot entry requires a buy signal")
    analyzed = _timestamp(proposal.get("analyzed_at"), "analysis")
    expires = _timestamp(proposal.get("expires_at"), "expiry")
    if analyzed > now + timedelta(seconds=5) or not analyzed < expires <= analyzed + timedelta(seconds=120):
        raise ValueError("invalid proposal lifetime")
    if expires <= now:
        raise ValueError("proposal has expired")
    position = _positive(proposal.get("position_eurc"), "position")
    reference = _positive(signal.get("last_price"), "entry")
    stop = _positive(signal.get("stop_loss"), "stop")
    target = _positive(signal.get("take_profit"), "target")
    if not stop < reference < target:
        raise ValueError("invalid exit direction for spot buy")
    validate_risk(position, reference, stop, target)
    execution = proposal.get("execution") or {}
    if execution.get("executable") is not True:
        raise ValueError("order book has not confirmed execution quality")
    # The visible limit is a price cap, never a promise of an immediate fill.
    # The default 20 bps cap matches the existing execution-quality guardrail.
    limits = RiskLimits()
    limit_price = min(
        reference * 1.002,
        (target + limits.min_reward_risk * stop) / (1 + limits.min_reward_risk),
        stop / (1 - limits.max_stop_pct),
    )
    limit_price = math.nextafter(limit_price, reference)
    average = _positive(execution.get("average_price"), "order-book price")
    if average > limit_price:
        raise ValueError("order-book price exceeds entry limit")
    validate_risk(position, limit_price, stop, target)
    cost_bps = _positive(proposal.get("estimated_round_trip_cost_bps"), "cost estimate", allow_zero=True)
    costs = position * cost_bps / 10000
    fee_bps = _positive((proposal.get("opportunity") or {}).get("taker_fee_bps"), "fee rate", allow_zero=True)
    entry_fee = position * fee_bps / 10000
    if costs < 2 * entry_fee:
        raise ValueError("round-trip estimate does not include both trading fees")
    target_pnl = position * (target / limit_price - 1) - costs
    stop_pnl = position * (stop / limit_price - 1) - costs
    if target_pnl <= 0:
        raise ValueError("target does not cover estimated costs")
    return TradeIntent(
        proposal_id=identifier, pair=pair, api_pair=api_pair,
        analyzed_at=analyzed.isoformat(), expires_at=expires.isoformat(),
        position_eurc=position, reference_price_eurc=reference,
        entry_limit_eurc=limit_price, stop_trigger_eurc=stop,
        take_profit_eurc=target, entry_fee_allowance_eurc=entry_fee,
        estimated_round_trip_cost_eurc=costs,
        estimated_target_pnl_eurc=target_pnl, estimated_stop_pnl_eurc=stop_pnl,
    )


def recheck_approved_intent(
    proposal: Mapping, approved_fingerprint: str, *,
    current_ask: float, quote_time: datetime, available_eurc: float,
    estimated_entry_fee_eurc: float, estimated_round_trip_cost_eurc: float,
    now: datetime | None = None,
) -> TradeIntent:
    """Fail closed on changed terms, stale data, a crossed stop, or low balance.

    Called by a future executor immediately before sending a price-limited order.
    The account balance supplied here must be free EURC after existing holds.
    """
    now = now or datetime.now(timezone.utc)
    intent = build_trade_intent(proposal, now=now)
    if intent.fingerprint != approved_fingerprint:
        raise ValueError("terms changed; a new approval is required")
    quote_time = _timestamp(quote_time, "quote")
    age = (now - quote_time).total_seconds()
    if not 0 <= age <= 10:
        raise ValueError("quote is stale or from the future")
    ask = _positive(current_ask, "current ask")
    if ask > intent.entry_limit_eurc or ask <= intent.stop_trigger_eurc:
        raise ValueError("price has left the approved entry bounds")
    fee = _positive(estimated_entry_fee_eurc, "entry fee", allow_zero=True)
    total_cost = _positive(estimated_round_trip_cost_eurc, "updated total cost", allow_zero=True)
    if fee > intent.entry_fee_allowance_eurc or total_cost > intent.estimated_round_trip_cost_eurc or total_cost < 2 * fee:
        raise ValueError("fees exceed the reviewed cost allowance")
    available = _positive(available_eurc, "available EURC", allow_zero=True)
    if available < intent.position_eurc + fee:
        raise ValueError("insufficient available EURC including fees")
    return intent
