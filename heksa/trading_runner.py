"""Build reviewable Kraken trade proposals from fresh public market data.

The runner selects EURC markets automatically, combines live market quality,
technical confidence and conservative historical feedback, and never submits
a live order.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from typing import TYPE_CHECKING
from uuid import uuid4

from .execution_quality import assess_execution
from .indicator_engine import analyze_regime
from .kraken_market import fetch_close_prices, fetch_ohlcv
from .market_analysis import analyze_prices
from .market_config import TRADING_QUOTE, require_eurc_pair
from .pair_scanner import rank_eurc_pairs
from .risk import performance_size_multiplier, suggest_position_eurc, validate_risk

if TYPE_CHECKING:
    from .journal import SignalJournal


def build_market_proposal(
    pair: str = "XBT/EURC",
    position_eurc: float | None = None,
    api_pair: str | None = None,
    risk_size_multiplier: float = 1.0,
) -> dict:
    display_pair = require_eurc_pair(pair)
    request_pair = require_eurc_pair(api_pair or pair)
    prices = fetch_close_prices(request_pair, interval=5)
    signal = analyze_prices(prices)

    if signal.signal == "WAIT":
        return {
            "quote_currency": TRADING_QUOTE,
            "pair": display_pair,
            "api_pair": request_pair,
            "status": "WAIT",
            "signal": asdict(signal),
            "confirmation": None,
            "requires_user_approval": False,
            "live_order_submitted": False,
        }

    confirmation_prices = fetch_close_prices(request_pair, interval=15)
    confirmation = analyze_prices(
        confirmation_prices,
        fast_window=6,
        slow_window=18,
        momentum_window=4,
        min_confidence=15.0,
    )

    if confirmation.signal != signal.signal:
        return {
            "pair": display_pair,
            "api_pair": request_pair,
            "status": "WAIT",
            "reason": "timeframe_disagreement",
            "quote_currency": TRADING_QUOTE,
            "signal": asdict(signal),
            "confirmation": asdict(confirmation),
            "requires_user_approval": False,
            "live_order_submitted": False,
        }

    side = "buy" if signal.signal == "BUY_CANDIDATE" else "sell"
    regime = analyze_regime(
        fetch_ohlcv(request_pair, interval=15, limit=100),
        side=side,
    )

    if regime.available and (
        not regime.direction_ok
        or not regime.volatility_ok
        or regime.score_multiplier <= 0.0
    ):
        return {
            "pair": display_pair,
            "api_pair": request_pair,
            "status": "WAIT",
            "reason": "regime_filter",
            "quote_currency": TRADING_QUOTE,
            "signal": asdict(signal),
            "confirmation": asdict(confirmation),
            "regime": regime.to_dict(),
            "requires_user_approval": False,
            "live_order_submitted": False,
        }

    if position_eurc is not None:
        selected_position_eurc = float(position_eurc)
    else:
        base_position = suggest_position_eurc(signal.confidence)
        regime_size_multiplier = (
            min(1.0, max(0.0, regime.score_multiplier))
            if regime.available
            else 1.0
        )
        selected_position_eurc = round(
            max(
                0.01,
                base_position
                * max(0.0, min(1.0, risk_size_multiplier))
                * regime_size_multiplier,
            ),
            2,
        )

    validate_risk(
        position_eurc=selected_position_eurc,
        entry=signal.last_price,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
    )

    return {
        "quote_currency": TRADING_QUOTE,
        "pair": display_pair,
        "api_pair": request_pair,
        "status": "PROPOSAL",
        "position_eurc": selected_position_eurc,
        "risk_size_multiplier": (
            1.0 if position_eurc is not None else max(0.0, min(1.0, risk_size_multiplier))
        ),
        "signal": asdict(signal),
        "confirmation": asdict(confirmation),
        "regime": regime.to_dict(),
        "requires_user_approval": True,
        "live_order_submitted": False,
    }


def _signal_side(signal_name: str) -> str | None:
    if signal_name == "BUY_CANDIDATE":
        return "buy"
    if signal_name == "SELL_CANDIDATE":
        return "sell"
    return None


def build_best_eurc_proposals(
    limit: int = 5,
    position_eurc: float | None = None,
    scan_multiplier: int = 3,
    journal: "SignalJournal | None" = None,
    entry_side: str | None = None,
) -> dict:
    """Scan EURC markets and rank final candidates using live + historical quality."""
    if entry_side not in {None, "buy", "sell"}:
        raise ValueError("entry_side must be buy or sell")
    scan_limit = max(limit * max(scan_multiplier, 1), limit, 1)
    rejected_pairs = journal.rejected_pairs() if journal is not None else set()
    # Make room for replacements before applying the analysis budget. Otherwise
    # repeated dismissals could leave the scanner stuck on the same top markets.
    selected_assets = journal.market_selection() if journal is not None else None
    ranked = rank_eurc_pairs(
        limit=scan_limit + len(rejected_pairs), allowed_assets=selected_assets,
    )
    opportunities = [item for item in ranked if item.pair.upper() not in rejected_pairs][:scan_limit]
    proposals: list[dict] = []

    recent_performance = (
        journal.recent_performance(limit=10)
        if journal is not None
        else {
            "closed_count": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0.0,
            "pnl_eurc": 0.0,
            "avg_return_pct": 0.0,
            "consecutive_losses": 0,
        }
    )
    risk_multiplier = performance_size_multiplier(recent_performance)

    for opportunity in opportunities:
        analysis_started_at = datetime.now(timezone.utc).isoformat()
        try:
            proposal = build_market_proposal(
                pair=opportunity.pair,
                api_pair=opportunity.api_pair,
                position_eurc=position_eurc,
                risk_size_multiplier=risk_multiplier,
            )
        except (RuntimeError, ValueError) as error:
            proposals.append(
                {
                    "pair": opportunity.pair,
                    "api_pair": opportunity.api_pair,
                    "status": "SKIPPED",
                    "reason": str(error),
                    "opportunity": opportunity.to_dict(),
                    "history": None,
                    "final_score": 0.0,
                    "live_order_submitted": False,
                }
            )
            continue

        opportunity_data = opportunity.to_dict()
        proposal["opportunity"] = opportunity_data

        signal_name = str(proposal["signal"].get("signal") or "")
        if (proposal.get("status") == "PROPOSAL" and entry_side is not None
                and _signal_side(signal_name) != entry_side):
            proposal.update(status="FILTERED", reason="not_an_entry_signal", requires_user_approval=False)
        confidence = float(proposal["signal"].get("confidence", 0.0))
        market_score = float(opportunity_data.get("opportunity_score", 0.0))

        history = None
        history_multiplier = 1.0
        if journal is not None:
            history = journal.pair_performance(
                opportunity.pair,
                side=_signal_side(signal_name),
            )
            history_multiplier = float(history.get("ranking_multiplier", 1.0))

        proposal["history"] = history
        proposal["history_multiplier"] = history_multiplier
        regime_data = proposal.get("regime") or {}
        regime_multiplier = float(regime_data.get("score_multiplier", 1.0))
        proposal["regime_multiplier"] = regime_multiplier
        proposal["final_score"] = (
            market_score
            * (confidence / 100.0)
            * history_multiplier
            * regime_multiplier
        )

        if proposal.get("status") == "PROPOSAL":
            entry = float(proposal["signal"].get("last_price", 0.0))
            target = float(proposal["signal"].get("take_profit", entry))
            reward_bps = (
                abs(target - entry) / entry * 10_000.0
                if entry > 0
                else 0.0
            )
            total_cost_bps = float(
                opportunity_data.get(
                    "estimated_round_trip_cost_bps",
                    opportunity_data.get("spread_bps", 0.0),
                )
            )
            cost_efficiency = (
                reward_bps / max(total_cost_bps, 0.1)
                if reward_bps > 0
                else 0.0
            )
            proposal["reward_bps"] = reward_bps
            proposal["estimated_round_trip_cost_bps"] = total_cost_bps
            proposal["cost_efficiency"] = cost_efficiency

            if cost_efficiency < 2.0:
                proposal["status"] = "FILTERED"
                proposal["reason"] = "total_trading_cost_too_high"
                proposal["requires_user_approval"] = False
                proposal["final_score"] = 0.0

        if journal is not None and proposal.get("status") == "PROPOSAL":
            gate = journal.signal_gate(
                opportunity.pair,
                side=_signal_side(signal_name) or "",
            )
            proposal["signal_gate"] = gate
            if not gate.get("allowed"):
                proposal["status"] = "FILTERED"
                proposal["reason"] = gate.get("reason")
                proposal["requires_user_approval"] = False
                proposal["final_score"] = 0.0

        if proposal.get("status") == "PROPOSAL":
            side = _signal_side(signal_name)
            if side is None:
                proposal["status"] = "FILTERED"
                proposal["reason"] = "invalid_signal_side"
                proposal["requires_user_approval"] = False
                proposal["final_score"] = 0.0
            else:
                try:
                    execution = assess_execution(
                        opportunity.pair,
                        side=side,
                        position_eurc=float(proposal.get("position_eurc") or 0.0),
                    )
                    proposal["execution"] = execution.to_dict()

                    if not execution.executable:
                        proposal["status"] = "FILTERED"
                        proposal["reason"] = "poor_execution_quality"
                        proposal["requires_user_approval"] = False
                        proposal["final_score"] = 0.0
                    else:
                        directional_imbalance = (
                            execution.book_imbalance
                            if side == "buy"
                            else -execution.book_imbalance
                        )
                        book_multiplier = max(
                            0.90,
                            min(1.10, 1.0 + directional_imbalance * 0.10),
                        )
                        proposal["book_multiplier"] = book_multiplier
                        proposal["final_score"] *= book_multiplier
                except (RuntimeError, ValueError) as error:
                    proposal["status"] = "FILTERED"
                    proposal["reason"] = "execution_check_failed"
                    proposal["execution_error"] = str(error)
                    proposal["requires_user_approval"] = False
                    proposal["final_score"] = 0.0

        proposal["proposal_id"] = uuid4().hex
        proposal["analyzed_at"] = analysis_started_at
        proposals.append(proposal)

    proposals.sort(
        key=lambda item: (
            item.get("status") == "PROPOSAL",
            float(item.get("final_score", 0.0)),
        ),
        reverse=True,
    )

    actionable_items = [item for item in proposals if item.get("status") == "PROPOSAL"]
    non_actionable_items = [item for item in proposals if item.get("status") != "PROPOSAL"]
    selected = (actionable_items + non_actionable_items)[:limit]
    actionable = len(actionable_items[:limit])

    return {
        "quote_currency": TRADING_QUOTE,
        "requested_limit": limit,
        "selected_assets": sorted(selected_assets) if selected_assets is not None else None,
        "markets_scanned": len(opportunities),
        "rejected_pairs_skipped": sum(item.pair.upper() in rejected_pairs for item in ranked),
        "actionable_candidates": actionable,
        "uses_historical_feedback": journal is not None,
        "recent_performance": recent_performance,
        "risk_size_multiplier": risk_multiplier,
        "proposals": selected,
        "live_order_submitted": False,
    }


def main() -> None:
    print(json.dumps(build_best_eurc_proposals(), indent=2))


if __name__ == "__main__":
    main()
