"""The application's trading currency is EURC; fiat valuation is separate."""

TRADING_QUOTE = "EURC"
FIAT_ASSETS = frozenset({
    "EUR", "USD", "GBP", "CAD", "AUD", "JPY", "CHF", "BRL", "ARS",
    "ZEUR", "ZUSD", "ZGBP", "ZCAD", "ZAUD", "ZJPY", "ZCHF",
})

# These are user-selectable watchlist entries, not a claim that a direct EURC
# market exists. Availability always comes from Kraken's AssetPairs endpoint.
WATCHLIST_ASSETS = {
    "XLM": "Stellar", "XRP": "XRP", "ETH": "Ethereum", "SOL": "Solana",
    "BTC": "Bitcoin", "ALGO": "Algorand", "HBAR": "Hedera",
    "ZBCN": "Zebec Network", "FLR": "Flare", "XDC": "XDC Network",
    "ADA": "Cardano", "LINK": "Chainlink", "AVAX": "Avalanche",
}


def base_symbol(pair: str) -> str:
    normalized = require_eurc_pair(pair)
    base = normalized.split("/", 1)[0] if "/" in normalized else normalized[:-4]
    return {"XBT": "BTC", "XXBT": "BTC", "XETH": "ETH", "XDG": "DOGE"}.get(base, base)


def fetch_market_catalog() -> list[dict]:
    from .kraken_market import fetch_spot_pairs

    available = {}
    for pair in fetch_spot_pairs(TRADING_QUOTE):
        try:
            available[base_symbol(pair)] = pair
        except ValueError:
            continue
    symbols = list(WATCHLIST_ASSETS) + sorted(set(available) - set(WATCHLIST_ASSETS))
    return [
        {"symbol": symbol, "name": WATCHLIST_ASSETS.get(symbol, symbol),
         "pair": available.get(symbol), "available": symbol in available}
        for symbol in symbols
    ]


def require_eurc_pair(pair: str) -> str:
    """Reject fiat markets and accidental EUR fallbacks before any order path."""
    normalized = pair.strip().upper()
    if "/" in normalized:
        base, quote = normalized.rsplit("/", 1)
        if "/" in base or quote != TRADING_QUOTE:
            raise ValueError("NexTrade obsługuje wyłącznie pary krypto/EURC.")
    elif normalized.endswith(TRADING_QUOTE):
        base = normalized[:-len(TRADING_QUOTE)]
    else:
        raise ValueError("NexTrade obsługuje wyłącznie pary krypto/EURC.")
    if not base or base in FIAT_ASSETS or base == TRADING_QUOTE:
        raise ValueError("Waluta bazowa musi być kryptowalutą inną niż EURC.")
    return normalized
