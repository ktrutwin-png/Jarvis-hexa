"""Read-only Kraken portfolio valuation in EURC."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite

from .kraken import KrakenClient
from .kraken_market import fetch_spot_pairs, fetch_tickers, ticker_for_pair


@dataclass(frozen=True)
class HoldingValue:
    asset: str
    amount: float
    price_eurc: float
    value_eurc: float

    def to_dict(self) -> dict:
        return asdict(self)


def _asset_key(asset: str) -> str:
    """Normalize Kraken balance suffixes while preserving the internal asset code."""
    return asset.strip().upper().split(".", 1)[0]


def eurc_price_map() -> dict[str, float]:
    """Build internal Kraken asset-code -> last EURC price mapping."""
    pairs = fetch_spot_pairs("EURC")
    tickers = fetch_tickers()

    prices: dict[str, float] = {
        "EURC": 1.0,
    }

    for pair_info in pairs.values():
        base = _asset_key(str(pair_info.get("base") or ""))
        if not base:
            continue

        ticker = ticker_for_pair(pair_info, tickers)
        if ticker is None:
            continue

        try:
            last = float(ticker.get("c", [0])[0])
        except (TypeError, ValueError, IndexError):
            continue

        if isfinite(last) and last > 0:
            prices[base] = last

    # Indicative valuation only: derive missing EURC prices from actual EUR
    # market prices and the live EURC/EUR rate. This never routes an order or
    # adds a synthetic market to the EURC trading universe.
    try:
        euro_pairs = fetch_spot_pairs("EUR")
    except RuntimeError:
        return prices
    euro_prices = {}
    for info in euro_pairs.values():
        ticker = ticker_for_pair(info, tickers)
        try:
            price = float(ticker["c"][0]) if ticker else 0.0
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        base = _asset_key(str(info.get("base") or ""))
        if base and isfinite(price) and price > 0:
            euro_prices[base] = price
    eurc_eur = euro_prices.get("EURC")
    if eurc_eur:
        prices["EUR"] = prices["ZEUR"] = 1.0 / eurc_eur
        for asset, euro_price in euro_prices.items():
            converted = euro_price / eurc_eur
            if isfinite(converted) and converted > 0:
                prices.setdefault(asset, converted)

    return prices


def value_balances_eurc(
    balances: dict[str, str],
    prices: dict[str, float] | None = None,
) -> dict:
    """Convert a Kraken balance response into an EURC portfolio snapshot."""
    price_map = prices if prices is not None else eurc_price_map()
    holdings: list[HoldingValue] = []
    unpriced: list[dict] = []

    for asset, raw_amount in balances.items():
        try:
            amount = float(raw_amount)
        except (TypeError, ValueError):
            continue

        if not isfinite(amount) or amount == 0:
            continue

        key = _asset_key(asset)
        price = price_map.get(key)
        if price is None or not isfinite(price) or price <= 0:
            unpriced.append({"asset": asset, "amount": amount})
            continue

        value = amount * price
        if not isfinite(value):
            unpriced.append({"asset": asset, "amount": amount})
            continue
        holdings.append(
            HoldingValue(
                asset=asset,
                amount=amount,
                price_eurc=price,
                value_eurc=value,
            )
        )

    holdings.sort(key=lambda item: item.value_eurc, reverse=True)

    return {
        "currency": "EURC",
        "total_eurc": sum(item.value_eurc for item in holdings),
        "holdings": [item.to_dict() for item in holdings],
        "unpriced": unpriced,
    }


def fetch_portfolio_eurc(client: KrakenClient | None = None) -> dict:
    """Fetch private balances and value holdings in EURC using market prices."""
    kraken = client or KrakenClient()
    return value_balances_eurc(kraken.balances())
