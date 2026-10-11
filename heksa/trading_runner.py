"""Build a reviewable Kraken trade proposal from fresh public market data.

This runner never submits a live order.
"""
from __future__ import annotations

from dataclasses import asdict
import json

from .kraken_market import fetch_close_prices
from .market_analysis import analyze_prices
from .risk import validate_risk


def build_market_proposal(pair: str = "XRPEUR", position_eur: float = 10.0) -> dict:
    prices = fetch_close_prices(pair)
    signal = analyze_prices(prices)

    if signal.signal == "WAIT":
        return {
            "pair": pair.upper(),
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
        side="buy" if signal.signal == "BUY_CANDIDATE" else "sell",
    )

    return {
        "pair": pair.upper(),
        "status": "PROPOSAL",
        "position_eur": position_eur,
        "signal": asdict(signal),
        "requires_user_approval": True,
        "live_order_submitted": False,
    }


def main() -> None:
    print(json.dumps(build_market_proposal(), indent=2))


if __name__ == "__main__":
    main()
