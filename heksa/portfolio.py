"""Read-only Kraken portfolio valuation in EUR."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .kraken import KrakenClient
from .kraken_market import fetch_spot_pairs, fetch_tickers, ticker_for_pair


@dataclass(frozen=True)
class HoldingValue:
    asset: str
    amount: float
    price_eur: float
    value_eur: float

    def to_dict(self) -> dict:
        return asdict(self)


def _asset_key(asset: str) -> str:
    """Normalize Kraken balance suffixes while preserving the internal asset code."""
    return asset.strip().upper().split(".", 1)[0]


def eur_price_map() -> dict[str, float]:
    """Build internal Kraken asset-code -> last EUR price mapping."""
    pairs = fetch_spot_pairs("EUR")
    tickers = fetch_tickers()

    prices: dict[str, float] = {
        "EUR": 1.0,
        "ZEUR": 1.0,
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

        if last > 0:
            prices[base] = last

    return prices


def value_balances_eur(
    balances: dict[str, str],
    prices: dict[str, float] | None = None,
) -> dict:
    """Convert a Kraken balance response into an EUR portfolio snapshot."""
    price_map = prices or eur_price_map()
    holdings: list[HoldingValue] = []
    unpriced: list[dict] = []

    for asset, raw_amount in balances.items():
        try:
            amount = float(raw_amount)
        except (TypeError, ValueError):
            continue

        if amount == 0:
            continue

        key = _asset_key(asset)
        price = price_map.get(key)
        if price is None:
            unpriced.append({"asset": asset, "amount": amount})
            continue

        value = amount * price
        holdings.append(
            HoldingValue(
                asset=asset,
                amount=amount,
                price_eur=price,
                value_eur=value,
            )
        )

    holdings.sort(key=lambda item: item.value_eur, reverse=True)

    return {
        "currency": "EUR",
        "total_eur": sum(item.value_eur for item in holdings),
        "holdings": [item.to_dict() for item in holdings],
        "unpriced": unpriced,
    }


def fetch_portfolio_eur(client: KrakenClient | None = None) -> dict:
    """Fetch private balances and value all directly-priced EUR holdings."""
    kraken = client or KrakenClient()
    return value_balances_eur(kraken.balances())
