"""Public Kraken market-data access.

Uses Kraken's public REST endpoints only. No private credentials are required.
"""
from __future__ import annotations

import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


KRAKEN_PUBLIC_BASE = "https://api.kraken.com/0/public"
KRAKEN_OHLC_API = f"{KRAKEN_PUBLIC_BASE}/OHLC"
KRAKEN_ASSET_PAIRS_API = f"{KRAKEN_PUBLIC_BASE}/AssetPairs"
KRAKEN_TICKER_API = f"{KRAKEN_PUBLIC_BASE}/Ticker"
KRAKEN_PRE_TRADE_API = f"{KRAKEN_PUBLIC_BASE}/PreTrade"

_CACHE: dict[str, tuple[float, dict]] = {}


def _public_get(
    endpoint: str,
    params: dict | None = None,
    cache_ttl: float = 0.0,
    retries: int = 2,
) -> dict:
    query = urlencode(params or {})
    url = f"{endpoint}?{query}" if query else endpoint
    now = time.monotonic()

    cached = _CACHE.get(url)
    if cached and cache_ttl > 0 and now - cached[0] <= cache_ttl:
        return cached[1]

    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Heksa-NexTrade/0.1",
        },
    )

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=12) as response:
                payload = json.load(response)

            errors = payload.get("error") or []
            if errors:
                message = "; ".join(errors)
                if "Rate limit" in message and attempt < retries:
                    time.sleep(1.0 + attempt)
                    continue
                raise RuntimeError(message)

            result = payload.get("result")
            if not isinstance(result, dict):
                raise RuntimeError("Kraken returned no usable result")

            if cache_ttl > 0:
                _CACHE[url] = (time.monotonic(), result)
            return result

        except HTTPError as error:
            last_error = error
            if error.code == 429 and attempt < retries:
                retry_after = error.headers.get("Retry-After")
                try:
                    delay = max(1.0, float(retry_after))
                except (TypeError, ValueError):
                    delay = 1.0 + attempt
                time.sleep(delay)
                continue
            raise RuntimeError(f"Kraken HTTP error: {error.code}") from error
        except URLError as error:
            last_error = error
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise RuntimeError(f"Kraken network error: {error.reason}") from error

    raise RuntimeError("Kraken request failed") from last_error


def fetch_ohlcv(pair: str, interval: int = 5, limit: int = 100) -> list[dict]:
    """Return normalized OHLCV candles from Kraken public market data."""
    result = _public_get(
        KRAKEN_OHLC_API,
        {"pair": pair.strip().upper(), "interval": interval},
        cache_ttl=20.0,
    )

    series = next((value for key, value in result.items() if key != "last"), None)
    if not series:
        raise RuntimeError("Kraken returned no OHLC data")

    candles: list[dict] = []
    for candle in series[-limit:]:
        try:
            candles.append(
                {
                    "time": int(float(candle[0])),
                    "open": float(candle[1]),
                    "high": float(candle[2]),
                    "low": float(candle[3]),
                    "close": float(candle[4]),
                    "vwap": float(candle[5]),
                    "volume": float(candle[6]),
                    "count": int(candle[7]),
                }
            )
        except (TypeError, ValueError, IndexError):
            continue

    if not candles:
        raise RuntimeError("Kraken returned no usable OHLC candles")
    return candles


def fetch_close_prices(pair: str, interval: int = 5, limit: int = 100) -> list[float]:
    result = _public_get(
        KRAKEN_OHLC_API,
        {"pair": pair.strip().upper(), "interval": interval},
        cache_ttl=20.0,
    )

    series = next((value for key, value in result.items() if key != "last"), None)
    if not series:
        raise RuntimeError("Kraken returned no OHLC data")

    closes = [float(candle[4]) for candle in series]
    return closes[-limit:]


def fetch_spot_pairs(quote: str = "EURC") -> dict[str, dict]:
    """Return active Kraken spot pairs for the requested display quote currency.

    Kraken uses legacy internal asset codes in some REST fields, while wsname
    exposes the human-readable market name. Filtering by the display name
    keeps discovery independent of those internal codes.
    """
    wanted_quote = quote.strip().upper()
    pairs = _public_get(
        KRAKEN_ASSET_PAIRS_API,
        {"assetVersion": 1, "aclass_base": "currency"},
        cache_ttl=300.0,
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
    return _public_get(
        KRAKEN_TICKER_API,
        {"assetVersion": 1},
        cache_ttl=10.0,
    )


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
        cache_ttl=1.0,
    )
    if not isinstance(result.get("bids"), list) or not isinstance(result.get("asks"), list):
        raise RuntimeError("Kraken returned no usable order book")
    return result
