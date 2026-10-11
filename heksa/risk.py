"""Risk guardrails for reviewable trade proposals."""
from __future__ import annotations

from dataclasses import dataclass


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
) -> None:
    if position_eur <= 0 or position_eur > limits.max_position_eur:
        raise ValueError("position size outside configured limit")
    risk = abs(entry - stop_loss)
    reward = abs(take_profit - entry)
    if entry <= 0 or risk <= 0:
        raise ValueError("invalid entry or stop")
    if risk / entry > limits.max_stop_pct:
        raise ValueError("stop distance exceeds configured limit")
    if reward / risk < limits.min_reward_risk:
        raise ValueError("reward/risk below configured minimum")
