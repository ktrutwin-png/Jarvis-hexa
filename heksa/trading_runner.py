"""Build a reviewable Kraken trade proposal from fresh public market data.

This runner never submits a live order.
"""
from __future__ import annotations

from dataclasses import asdict
import json

from .kraken_market import fetch_close_prices
from .market_analysis import analyze_prices


def build_market_proposal(pair: str = "XRPEUR") -> dict:
    prices = fetch_close_prices(pair)
    signal = analyze_prices(prices)
    return {
        "pair": pair.upper(),
        "signal": asdict(signal),
        "requires_user_approval": True,
        "live_order_submitted": False,
    }


def main() -> None:
    print(json.dumps(build_market_proposal(), indent=2))


if __name__ == "__main__":
    main()
