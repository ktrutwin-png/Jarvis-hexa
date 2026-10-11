"""Public Kraken market-data access.

No private credentials are required for OHLC market data.
"""
from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import urlopen


KRAKEN_PUBLIC_API = "https://api.kraken.com/0/public/OHLC"


def fetch_close_prices(pair: str, interval: int = 5, limit: int = 100) -> list[float]:
    query = urlencode({"pair": pair.strip().upper(), "interval": interval})
    with urlopen(f"{KRAKEN_PUBLIC_API}?{query}", timeout=10) as response:
        payload = json.load(response)

    errors = payload.get("error") or []
    if errors:
        raise RuntimeError("; ".join(errors))

    result = payload.get("result", {})
    series = next((value for key, value in result.items() if key != "last"), None)
    if not series:
        raise RuntimeError("Kraken returned no OHLC data")

    closes = [float(candle[4]) for candle in series]
    return closes[-limit:]
