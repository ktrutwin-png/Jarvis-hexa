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
KRAKEN_PRE_TRADE_API = f"{KRAKEN_PUBLIC_BASE}/PreTrade"


def _public_get(endpoint: str, params: dict | None = None) -> dict:
    query = urlencode(params or {})
    url = f"{endpoint}?{query}" if query else endpoint
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Heksa-NexTrade/0.1",
        },
    )

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
    """Return active Kraken spot pairs for the requested display quote currency.

    Kraken uses legacy internal asset codes in some REST fields, while wsname
    exposes the human-readable market name. Filtering by the display name
    keeps EUR discovery independent of those internal codes.
    """
    wanted_quote = quote.strip().upper()
    pairs = _public_get(
        KRAKEN_ASSET_PAIRS_API,
        {"assetVersion": 1, "aclass_base": "currency"},
    )

    selected: dict[str, dict] = {}
    for api_name, raw_info in pairs.items():
        if not isinstance(raw_info, dict):
            continue
        if str(raw_info.get("status", "")).lower() != "online":
            continue

        wsname = str(raw_info.get("wsname") or "").upper()
        altname = str(raw_info.get("altname") or api_name).upper()
        display_name = wsname or altname

        if "/" in display_name:
            display_quote = display_name.rsplit("/", 1)[-1]
        elif display_name.endswith(wanted_quote):
            display_quote = wanted_quote
        else:
            continue

        if display_quote != wanted_quote:
            continue

        info = dict(raw_info)
        info["_api_name"] = str(api_name).upper()
        info["_altname"] = altname
        info["_display_name"] = display_name
        selected[display_name] = info

    return selected


def fetch_tickers() -> dict[str, dict]:
    """Return current ticker information for tradeable spot markets."""
    return _public_get(KRAKEN_TICKER_API, {"assetVersion": 1})


def ticker_for_pair(pair_info: dict, tickers: dict[str, dict]) -> dict | None:
    """Find ticker data regardless of which Kraken pair alias the response uses."""
    aliases = [
        str(pair_info.get("_api_name") or "").upper(),
        str(pair_info.get("_altname") or pair_info.get("altname") or "").upper(),
        str(pair_info.get("_display_name") or pair_info.get("wsname") or "").upper(),
    ]

    expanded: list[str] = []
    for alias in aliases:
        if not alias:
            continue
        expanded.append(alias)
        expanded.append(alias.replace("/", ""))

    for alias in expanded:
        ticker = tickers.get(alias)
        if isinstance(ticker, dict):
            return ticker

    return None


def fetch_pretrade(symbol: str) -> dict:
    """Return Kraken aggregated top-of-book levels for one display symbol."""
    result = _public_get(
        KRAKEN_PRE_TRADE_API,
        {"symbol": symbol.strip().upper()},
    )
    if not isinstance(result.get("bids"), list) or not isinstance(result.get("asks"), list):
        raise RuntimeError("Kraken returned no usable order book")
    return result
