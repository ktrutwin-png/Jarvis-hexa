"""EURC opportunity scanner for Kraken spot markets.

Ranks markets by a transparent opportunity score built from:
- 24h quote-volume liquidity,
- 24h price range,
- current bid/ask spread.

The score is a market-selection heuristic, not a profit guarantee.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite, log10

from .kraken_market import fetch_spot_pairs, fetch_tickers, ticker_for_pair
from .market_config import FIAT_ASSETS, TRADING_QUOTE, base_symbol, require_eurc_pair


@dataclass(frozen=True)
class PairOpportunity:
    pair: str
    api_pair: str
    last_price_eurc: float
    quote_volume_24h_eurc: float
    range_24h_pct: float
    spread_bps: float
    taker_fee_bps: float
    estimated_round_trip_cost_bps: float
    opportunity_score: float
    market_rules: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _float_at(values, index: int, default: float = 0.0) -> float:
    try:
        return float(values[index])
    except (TypeError, ValueError, IndexError):
        return default


def _conservative_taker_fee_bps(pair_info: dict) -> float:
    """Use the highest published taker-fee tier as a conservative fallback."""
    fees = pair_info.get("fees") or []
    percentages: list[float] = []
    for row in fees:
        try:
            value = float(row[1])
            if isfinite(value) and value >= 0:
                percentages.append(value)
        except (TypeError, ValueError, IndexError):
            continue
    return max(percentages, default=0.40) * 100.0


def _score_pair(pair: str, pair_info: dict, ticker: dict) -> PairOpportunity | None:
    ask = _float_at(ticker.get("a"), 0)
    bid = _float_at(ticker.get("b"), 0)
    last = _float_at(ticker.get("c"), 0)
    volume_24h_base = _float_at(ticker.get("v"), 1)
    low_24h = _float_at(ticker.get("l"), 1)
    high_24h = _float_at(ticker.get("h"), 1)
    vwap_24h = _float_at(ticker.get("p"), 1, last)

    if not all(isfinite(value) for value in (
        ask, bid, last, volume_24h_base, low_24h, high_24h, vwap_24h
    )):
        return None
    if min(ask, bid, last, low_24h, high_24h, vwap_24h) <= 0:
        return None
    if bid > ask or high_24h < low_24h or volume_24h_base < 0:
        return None

    mid = (ask + bid) / 2.0
    spread_bps = ((ask - bid) / mid) * 10_000 if mid > 0 else 0.0
    range_pct = ((high_24h - low_24h) / low_24h) * 100.0
    quote_volume = volume_24h_base * (vwap_24h or last)
    taker_fee_bps = _conservative_taker_fee_bps(pair_info)
    estimated_round_trip_cost_bps = max(spread_bps, 0.0) + (2.0 * taker_fee_bps)

    liquidity_factor = max(1.0, log10(max(quote_volume, 1.0)))
    cost_penalty = 1.0 + estimated_round_trip_cost_bps / 50.0
    score = (max(range_pct, 0.0) * liquidity_factor) / cost_penalty

    if not all(isfinite(value) for value in (
        spread_bps, range_pct, quote_volume, estimated_round_trip_cost_bps, score
    )):
        return None

    return PairOpportunity(
        pair=pair,
        api_pair=str(pair_info.get("_altname") or pair_info.get("_api_name") or pair).upper(),
        last_price_eurc=last,
        quote_volume_24h_eurc=quote_volume,
        range_24h_pct=range_pct,
        spread_bps=spread_bps,
        taker_fee_bps=taker_fee_bps,
        estimated_round_trip_cost_bps=estimated_round_trip_cost_bps,
        opportunity_score=score,
        market_rules={key: pair_info.get(key) for key in (
            "wsname", "altname", "status", "pair_decimals", "lot_decimals",
            "lot_multiplier", "tick_size", "ordermin", "costmin")},
    )


def rank_eurc_pairs(
    limit: int = 12,
    min_quote_volume_eurc: float = 50_000.0,
    max_spread_bps: float = 80.0,
    allowed_assets: set[str] | None = None,
) -> list[PairOpportunity]:
    """Return the strongest currently tradeable Kraken EURC markets."""
    if limit <= 0:
        return []

    pairs = fetch_spot_pairs(TRADING_QUOTE)
    if not pairs:
        return []
    tickers = fetch_tickers()

    ranked: list[PairOpportunity] = []
    for pair, pair_info in pairs.items():
        if str(pair_info.get("base") or "").upper() in FIAT_ASSETS:
            continue
        try:
            require_eurc_pair(pair)
            if allowed_assets is not None and base_symbol(pair) not in allowed_assets:
                continue
        except ValueError:
            continue
        ticker = ticker_for_pair(pair_info, tickers)
        if ticker is None:
            continue

        opportunity = _score_pair(pair, pair_info, ticker)
        if opportunity is None:
            continue
        if opportunity.quote_volume_24h_eurc < min_quote_volume_eurc:
            continue
        if opportunity.spread_bps > max_spread_bps:
            continue

        ranked.append(opportunity)

    ranked.sort(key=lambda item: item.opportunity_score, reverse=True)
    return ranked[:limit]


def best_eurc_pairs(limit: int = 12, allowed_assets: set[str] | None = None) -> list[dict]:
    """JSON-friendly result for UI/agent consumption."""
    return [item.to_dict() for item in rank_eurc_pairs(limit=limit, allowed_assets=allowed_assets)]
