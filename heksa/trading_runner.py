"""Build reviewable Kraken trade proposals from fresh public market data.

The runner selects EUR markets automatically, combines market quality with
technical confidence, and never submits a live order.
"""
from __future__ import annotations

from dataclasses import asdict
import json

from .kraken_market import fetch_close_prices
from .market_analysis import analyze_prices
from .pair_scanner import rank_eur_pairs
from .risk import validate_risk


def build_market_proposal(
    pair: str = "XRP/EUR",
    position_eur: float = 10.0,
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

    validate_risk(
        position_eur=position_eur,
        entry=signal.last_price,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
    )

    return {
        "pair": display_pair,
        "api_pair": request_pair,
        "status": "PROPOSAL",
        "position_eur": position_eur,
        "signal": asdict(signal),
        "requires_user_approval": True,
        "live_order_submitted": False,
    }


def build_best_eur_proposals(
    limit: int = 5,
    position_eur: float = 10.0,
    scan_multiplier: int = 3,
) -> dict:
    """Scan EUR markets, analyze OHLC and rank the strongest final candidates."""
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
                    "final_score": 0.0,
                    "live_order_submitted": False,
                }
            )
            continue

        opportunity_data = opportunity.to_dict()
        proposal["opportunity"] = opportunity_data

        confidence = float(proposal["signal"].get("confidence", 0.0))
        market_score = float(opportunity_data.get("opportunity_score", 0.0))
        proposal["final_score"] = market_score * (confidence / 100.0)
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
        "proposals": selected,
        "live_order_submitted": False,
    }


def main() -> None:
    print(json.dumps(build_best_eur_proposals(), indent=2))


if __name__ == "__main__":
    main()
