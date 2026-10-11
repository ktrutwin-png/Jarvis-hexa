"""Risk guardrails for reviewable trade proposals."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class RiskLimits:
    max_position_eur: float = 10.0
    max_stop_pct: float = 0.01
    min_reward_risk: float = 1.5


def validate_risk(
    position_eur: float,
    entry: float,
    stop_loss: float,
    take_profit: float,
    limits: RiskLimits = RiskLimits(),
    side: str | None = None,
) -> None:
    numbers = (position_eur, entry, stop_loss, take_profit,
               limits.max_position_eur, limits.max_stop_pct, limits.min_reward_risk)
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not isfinite(value) or value <= 0 for value in numbers):
        raise ValueError("risk inputs and limits must be finite positive numbers")
    if limits.max_stop_pct >= 1:
        raise ValueError("stop percentage must be below one")
    if side not in {None, "buy", "sell"}:
        raise ValueError("side must be buy or sell")
    buy_levels = stop_loss < entry < take_profit
    sell_levels = take_profit < entry < stop_loss
    if not ((buy_levels and side in {None, "buy"})
            or (sell_levels and side in {None, "sell"})):
        raise ValueError("stop and target must match the trade direction")
    if position_eur <= 0 or position_eur > limits.max_position_eur:
        raise ValueError("position size outside configured limit")
    risk = abs(entry - stop_loss)
    reward = abs(take_profit - entry)
    if entry <= 0 or risk <= 0:
        raise ValueError("invalid entry or stop")
    if risk / entry > limits.max_stop_pct + 1e-12:
        raise ValueError("stop distance exceeds configured limit")
    if reward / risk < limits.min_reward_risk:
        raise ValueError("reward/risk below configured minimum")
