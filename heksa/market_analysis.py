"""Technical market analysis helpers for Kraken trade proposals.

Indicators are deterministic and transparent. The module never submits orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Iterable


@dataclass(frozen=True)
class MarketSignal:
    signal: str
    last_price: float
    fast_ma: float
    slow_ma: float
    momentum_pct: float
    volatility_pct: float
    confidence: float
    stop_loss: float
    take_profit: float


def _returns(values: list[float]) -> list[float]:
    result: list[float] = []
    for previous, current in zip(values, values[1:]):
        if previous > 0:
            result.append((current / previous) - 1.0)
    return result


def analyze_prices(
    prices: Iterable[float],
    fast_window: int = 9,
    slow_window: int = 21,
    momentum_window: int = 6,
    risk_pct: float = 0.01,
    reward_pct: float = 0.02,
    min_confidence: float = 20.0,
) -> MarketSignal:
    values = [float(p) for p in prices]
    required = max(slow_window, momentum_window + 1)
    if len(values) < required:
        raise ValueError(f"need at least {required} prices")
    if any(value <= 0 for value in values[-required:]):
        raise ValueError("prices must be positive")

    last = values[-1]
    fast = mean(values[-fast_window:])
    slow = mean(values[-slow_window:])

    anchor = values[-(momentum_window + 1)]
    momentum_pct = ((last / anchor) - 1.0) * 100.0

    recent_returns = _returns(values[-(slow_window + 1):])
    volatility_pct = (pstdev(recent_returns) * 100.0) if len(recent_returns) > 1 else 0.0

    trend_pct = abs(fast - slow) / last * 100.0
    direction_up = fast > slow and momentum_pct > 0
    direction_down = fast < slow and momentum_pct < 0

    noise = max(volatility_pct, 0.05)
    raw_confidence = ((trend_pct * 2.0) + abs(momentum_pct)) / noise * 12.5
    confidence = max(0.0, min(100.0, raw_confidence))

    if direction_up and confidence >= min_confidence:
        signal = "BUY_CANDIDATE"
    elif direction_down and confidence >= min_confidence:
        signal = "SELL_CANDIDATE"
    else:
        signal = "WAIT"

    adaptive_stop_pct = max(0.003, min(risk_pct, (volatility_pct / 100.0) * 1.5))
    adaptive_reward_pct = max(reward_pct, adaptive_stop_pct * 2.0)

    if signal == "BUY_CANDIDATE":
        stop = last * (1.0 - adaptive_stop_pct)
        target = last * (1.0 + adaptive_reward_pct)
    elif signal == "SELL_CANDIDATE":
        stop = last * (1.0 + adaptive_stop_pct)
        target = last * (1.0 - adaptive_reward_pct)
    else:
        stop = last
        target = last

    return MarketSignal(
        signal=signal,
        last_price=last,
        fast_ma=fast,
        slow_ma=slow,
        momentum_pct=momentum_pct,
        volatility_pct=volatility_pct,
        confidence=confidence,
        stop_loss=stop,
        take_profit=target,
    )
