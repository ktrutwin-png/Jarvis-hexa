"""Public Kraken market-data access.

Uses Kraken's public REST endpoints only. No private credentials are required.
"""
from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen


KRAKEN_PUBLIC_BASE = "https://api.kraken.com/0/public"
KRAKEN_OHLC_API = f"{KRAKEN_PUBLIC_BASE}/OHLC"
KRAKEN_ASSET_PAIRS_API = f"{KRAKEN_PUBLIC_BASE}/AssetPairs"
KRAKEN_TICKER_API = f"{KRAKEN_PUBLIC_BASE}/Ticker"


def _public_get(endpoint: str, params: dict | None = None) -> dict:
    query = urlencode(params or {})
    url = f"{endpoint}?{query}" if query else endpoint
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "Heksa-NexTrade/0.1"})

    with urlopen(request, timeout=12) as response:
        payload = json.load(response)

    errors = payload.get("error") or []
    if errors:
        raise RuntimeError("; ".join(errors))

    result = payload.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("Kraken returned no usable result")

    return result


def fetch_close_prices(pair: str, interval: int = 5, limit: int = 100) -> list[float]:
    result = _public_get(
        KRAKEN_OHLC_API,
        {"pair": pair.strip().upper(), "interval": interval},
    )

    series = next((value for key, value in result.items() if key != "last"), None)
    if not series:
        raise RuntimeError("Kraken returned no OHLC data")

    closes = [float(candle[4]) for candle in series]
    return closes[-limit:]


def fetch_spot_pairs(quote: str = "EUR") -> dict[str, dict]:
    """Return active Kraken spot pairs for the requested quote currency."""
    wanted_quote = quote.strip().upper()
    pairs = _public_get(
        KRAKEN_ASSET_PAIRS_API,
        {"assetVersion": 1, "aclass_base": "currency"},
    )

    selected: dict[str, dict] = {}
    for pair_name, info in pairs.items():
        if not isinstance(info, dict):
            continue
        if str(info.get("quote", "")).upper() != wanted_quote:
            continue
        if str(info.get("status", "")).lower() != "online":
            continue

        display_name = str(info.get("wsname") or pair_name).upper()
        selected[display_name] = info

    return selected


def fetch_tickers() -> dict[str, dict]:
    """Return current ticker information for all tradeable spot markets."""
    return _public_get(KRAKEN_TICKER_API, {"assetVersion": 1})
