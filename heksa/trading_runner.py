"""Build reviewable Kraken trade proposals from fresh public market data.

The runner can select the strongest EUR markets automatically.
It never submits a live order.
"""
from __future__ import annotations

from dataclasses import asdict
import json

from .kraken_market import fetch_close_prices
from .market_analysis import analyze_prices
from .pair_scanner import rank_eur_pairs
from .risk import validate_risk


def build_market_proposal(pair: str = "XRP/EUR", position_eur: float = 10.0) -> dict:
    normalized_pair = pair.strip().upper()
    prices = fetch_close_prices(normalized_pair)
    signal = analyze_prices(prices)

    if signal.signal == "WAIT":
        return {
            "pair": normalized_pair,
            "status": "WAIT",
            "signal": asdict(signal),
            "requires_user_approval": False,
            "live_order_submitted": False,
        }

    validate_risk(
        position_eur=position_eur,
        entry=signal.last_price,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
    )

    return {
        "pair": normalized_pair,
        "status": "PROPOSAL",
        "position_eur": position_eur,
        "signal": asdict(signal),
        "requires_user_approval": True,
        "live_order_submitted": False,
    }


def build_best_eur_proposals(
    limit: int = 5,
    position_eur: float = 10.0,
) -> dict:
    """Scan Kraken EUR markets and build proposals for the strongest candidates."""
    opportunities = rank_eur_pairs(limit=max(limit, 1))
    proposals: list[dict] = []

    for opportunity in opportunities:
        try:
            proposal = build_market_proposal(
                pair=opportunity.pair,
                position_eur=position_eur,
            )
        except (RuntimeError, ValueError) as error:
            proposals.append(
                {
                    "pair": opportunity.pair,
                    "status": "SKIPPED",
                    "reason": str(error),
                    "opportunity": opportunity.to_dict(),
                    "live_order_submitted": False,
                }
            )
            continue

        proposal["opportunity"] = opportunity.to_dict()
        proposals.append(proposal)

    return {
        "quote_currency": "EUR",
        "requested_limit": limit,
        "markets_found": len(opportunities),
        "proposals": proposals,
        "live_order_submitted": False,
    }


def main() -> None:
    print(json.dumps(build_best_eur_proposals(), indent=2))


if __name__ == "__main__":
    main()
