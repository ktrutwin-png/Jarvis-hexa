"""Risk guardrails and position sizing for reviewable trade proposals."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskLimits:
    max_position_eurc: float = 10.0
    min_position_eurc: float = 2.0
    max_stop_pct: float = 0.01
    min_reward_risk: float = 1.5


def suggest_position_eurc(
    confidence: float,
    limits: RiskLimits = RiskLimits(),
) -> float:
    """Scale position size inside configured EURC limits using signal confidence."""
    bounded = max(0.0, min(100.0, float(confidence)))
    if bounded <= 0:
        return 0.0

    span = max(0.0, limits.max_position_eurc - limits.min_position_eurc)
    scaled = limits.min_position_eurc + span * (bounded / 100.0)
    return round(min(limits.max_position_eurc, max(limits.min_position_eurc, scaled)), 2)


def validate_risk(
    position_eurc: float,
    entry: float,
    stop_loss: float,
    take_profit: float,
    limits: RiskLimits = RiskLimits(),
) -> None:
    if position_eurc <= 0 or position_eurc > limits.max_position_eurc:
        raise ValueError("position size outside configured limit")
    risk = abs(entry - stop_loss)
    reward = abs(take_profit - entry)
    if entry <= 0 or risk <= 0:
        raise ValueError("invalid entry or stop")
    if risk / entry > limits.max_stop_pct:
        raise ValueError("stop distance exceeds configured limit")
    if reward / risk < limits.min_reward_risk:
        raise ValueError("reward/risk below configured minimum")


def performance_size_multiplier(recent: dict) -> float:
    """Reduce exposure after weak recent outcomes; never increase above 1.0."""
    closed = int(recent.get("closed_count") or 0)
    losses_in_row = int(recent.get("consecutive_losses") or 0)
    win_rate = float(recent.get("win_rate_pct") or 0.0)
    pnl_eurc = float(recent.get("pnl_eurc") or 0.0)

    if closed < 3:
        return 1.0
    if losses_in_row >= 5:
        return 0.35
    if losses_in_row >= 3:
        return 0.60
    if closed >= 6 and win_rate < 35.0:
        return 0.70
    if pnl_eurc < 0 and win_rate < 45.0:
        return 0.85
    return 1.0
