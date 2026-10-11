"""Optional technical-indicator adapter for NexTrade.

Uses talipp when available. The dependency is intentionally optional so the
core app still starts on minimal Android/Termux environments.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Iterable


@dataclass(frozen=True)
class RegimeSignal:
    available: bool
    source: str
    regime: str
    adx: float | None
    plus_di: float | None
    minus_di: float | None
    rsi: float | None
    atr_pct: float | None
    direction_ok: bool
    volatility_ok: bool
    score_multiplier: float

    def to_dict(self) -> dict:
        return asdict(self)


def _fallback_signal() -> RegimeSignal:
    return RegimeSignal(
        available=False,
        source="fallback",
        regime="unknown",
        adx=None,
        plus_di=None,
        minus_di=None,
        rsi=None,
        atr_pct=None,
        direction_ok=True,
        volatility_ok=True,
        score_multiplier=1.0,
    )


def analyze_regime(candles: Iterable[dict], side: str) -> RegimeSignal:
    """Analyze trend strength, direction, RSI and normalized ATR.

    Returns a neutral fallback when talipp is not installed or data is
    insufficient. This keeps market-data collection functional on minimal
    installations while still benefiting from the library when present.
    """
    values = list(candles)
    if len(values) < 40:
        return _fallback_signal()

    normalized_side = side.strip().lower()
    if normalized_side not in {"buy", "sell"}:
        return _fallback_signal()

    try:
        from talipp.indicators import ADX, ATR, RSI
        from talipp.ohlcv import OHLCV
    except ImportError:
        return _fallback_signal()

    try:
        ohlcv = [
            OHLCV(
                float(item["open"]),
                float(item["high"]),
                float(item["low"]),
                float(item["close"]),
                float(item.get("volume") or 0.0),
                datetime.fromtimestamp(
                    int(item.get("time") or 0),
                    tz=timezone.utc,
                ),
            )
            for item in values
        ]
        closes = [float(item["close"]) for item in values]

        rsi_ind = RSI(14, closes)
        atr_ind = ATR(14, ohlcv)
        adx_ind = ADX(14, 14, ohlcv)

        rsi = float(rsi_ind[-1])
        atr = float(atr_ind[-1])
        adx_value = adx_ind[-1]
        adx = float(adx_value.adx)
        plus_di = float(adx_value.plus_di)
        minus_di = float(adx_value.minus_di)
        last = closes[-1]
    except (TypeError, ValueError, IndexError, AttributeError):
        return _fallback_signal()

    atr_pct = (atr / last * 100.0) if last > 0 else 0.0
    regime = "trend" if adx >= 20.0 else "range"

    if normalized_side == "buy":
        direction_ok = plus_di > minus_di and rsi < 75.0
    else:
        direction_ok = minus_di > plus_di and rsi > 25.0

    volatility_ok = 0.10 <= atr_pct <= 6.0

    if not direction_ok or not volatility_ok:
        multiplier = 0.0
    else:
        trend_component = max(0.90, min(1.12, 0.90 + adx / 250.0))
        rsi_component = 1.0
        if normalized_side == "buy" and 50.0 <= rsi <= 68.0:
            rsi_component = 1.05
        elif normalized_side == "sell" and 32.0 <= rsi <= 50.0:
            rsi_component = 1.05
        multiplier = max(0.85, min(1.15, trend_component * rsi_component))

    return RegimeSignal(
        available=True,
        source="talipp",
        regime=regime,
        adx=adx,
        plus_di=plus_di,
        minus_di=minus_di,
        rsi=rsi,
        atr_pct=atr_pct,
        direction_ok=direction_ok,
        volatility_ok=volatility_ok,
        score_multiplier=multiplier,
    )
