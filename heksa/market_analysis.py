"""Market analysis helpers for Kraken order proposals.

Produces indicators and a neutral signal. It does not place trades.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Iterable


@dataclass(frozen=True)
class MarketSignal:
    signal: str
    last_price: float
    fast_ma: float
    slow_ma: float
    stop_loss: float
    take_profit: float


def analyze_prices(
    prices: Iterable[float],
    fast_window: int = 9,
    slow_window: int = 21,
    risk_pct: float = 0.01,
    reward_pct: float = 0.02,
) -> MarketSignal:
    values = [float(p) for p in prices]
    if len(values) < slow_window:
        raise ValueError(f"need at least {slow_window} prices")

    last = values[-1]
    fast = mean(values[-fast_window:])
    slow = mean(values[-slow_window:])

    if fast > slow:
        signal = "BUY_CANDIDATE"
        stop = last * (1 - risk_pct)
        target = last * (1 + reward_pct)
    elif fast < slow:
        signal = "SELL_CANDIDATE"
        stop = last * (1 + risk_pct)
        target = last * (1 - reward_pct)
    else:
        signal = "WAIT"
        stop = last
        target = last

    return MarketSignal(
        signal=signal,
        last_price=last,
        fast_ma=fast,
        slow_ma=slow,
        stop_loss=stop,
        take_profit=target,
    )
