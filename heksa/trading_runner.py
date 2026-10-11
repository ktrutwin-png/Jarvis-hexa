"""Build reviewable Kraken trade proposals from fresh public market data.

The runner selects EUR markets automatically, combines live market quality,
technical confidence and conservative historical feedback, and never submits
a live order.
"""
from __future__ import annotations

from dataclasses import asdict
import json
from typing import TYPE_CHECKING

from .kraken_market import fetch_close_prices
from .market_analysis import analyze_prices
from .pair_scanner import rank_eur_pairs
from .risk import suggest_position_eur, validate_risk

if TYPE_CHECKING:
    from .journal import SignalJournal


def build_market_proposal(
    pair: str = "XRP/EUR",
    position_eur: float | None = None,
    api_pair: str | None = None,
) -> dict:
    display_pair = pair.strip().upper()
    request_pair = (api_pair or pair).strip().upper()
    prices = fetch_close_prices(request_pair)
    signal = analyze_prices(prices)

    if signal.signal == "WAIT":
        return {
            "pair": display_pair,
            "api_pair": request_pair,
            "status": "WAIT",
            "signal": asdict(signal),
            "requires_user_approval": False,
            "live_order_submitted": False,
        }

    selected_position_eur = (
        float(position_eur)
        if position_eur is not None
        else suggest_position_eur(signal.confidence)
    )

    validate_risk(
        position_eur=selected_position_eur,
        entry=signal.last_price,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
    )

    return {
        "pair": display_pair,
        "api_pair": request_pair,
        "status": "PROPOSAL",
        "position_eur": selected_position_eur,
        "signal": asdict(signal),
        "requires_user_approval": True,
        "live_order_submitted": False,
    }


def _signal_side(signal_name: str) -> str | None:
    if signal_name == "BUY_CANDIDATE":
        return "buy"
    if signal_name == "SELL_CANDIDATE":
        return "sell"
    return None


def build_best_eur_proposals(
    limit: int = 5,
    position_eur: float | None = None,
    scan_multiplier: int = 3,
    journal: "SignalJournal | None" = None,
) -> dict:
    """Scan EUR markets and rank final candidates using live + historical quality."""
    scan_limit = max(limit * max(scan_multiplier, 1), limit, 1)
    opportunities = rank_eur_pairs(limit=scan_limit)
    proposals: list[dict] = []

    for opportunity in opportunities:
        try:
            proposal = build_market_proposal(
                pair=opportunity.pair,
                api_pair=opportunity.api_pair,
                position_eur=position_eur,
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
        proposal["final_score"] = (
            market_score
            * (confidence / 100.0)
            * history_multiplier
        )
        proposals.append(proposal)

    proposals.sort(
        key=lambda item: (
            item.get("status") == "PROPOSAL",
            float(item.get("final_score", 0.0)),
        ),
        reverse=True,
    )

    selected = proposals[:limit]
    actionable = sum(item.get("status") == "PROPOSAL" for item in selected)

    return {
        "quote_currency": "EUR",
        "requested_limit": limit,
        "markets_scanned": len(opportunities),
        "actionable_candidates": actionable,
        "uses_historical_feedback": journal is not None,
        "proposals": selected,
        "live_order_submitted": False,
    }


def main() -> None:
    print(json.dumps(build_best_eur_proposals(), indent=2))


if __name__ == "__main__":
    main()
