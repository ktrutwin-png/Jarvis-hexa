"""Exact spot-order sizing from Kraken AssetPairs, with no order submission."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
import hashlib
import json

from .market_config import base_symbol, require_eurc_pair
from .risk import RiskLimits


def amount(value, *, zero_allowed=False) -> Decimal:
    try:
        result = Decimal(str(value))
    except (ValueError, InvalidOperation):
        raise ValueError("invalid market-rule amount") from None
    if not result.is_finite() or result < 0 or (not zero_allowed and result == 0):
        raise ValueError("invalid market-rule amount")
    return result


def text(value: Decimal) -> str:
    formatted = format(value, "f")
    return formatted.rstrip("0").rstrip(".") if "." in formatted else formatted


def _places(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 18:
        raise ValueError("unsupported market precision")
    return value


@dataclass(frozen=True)
class MarketRules:
    pair: str
    price_step: str
    volume_step: str
    minimum_volume: str
    minimum_cost: str

    @classmethod
    def from_metadata(cls, pair: str, metadata: Mapping) -> "MarketRules":
        pair = require_eurc_pair(pair)
        if not isinstance(metadata, Mapping) or metadata.get("status") != "online":
            raise ValueError("market is not online")
        advertised = require_eurc_pair(str(metadata.get("wsname") or metadata.get("altname") or ""))
        if base_symbol(pair) != base_symbol(advertised):
            raise ValueError("market rules belong to another pair")
        if metadata.get("lot_multiplier") != 1 or isinstance(metadata.get("lot_multiplier"), bool):
            raise ValueError("unsupported lot multiplier")
        price_quantum = Decimal(1).scaleb(-_places(metadata.get("pair_decimals")))
        volume_step = Decimal(1).scaleb(-_places(metadata.get("lot_decimals")))
        price_step = amount(metadata.get("tick_size"))
        if price_step < price_quantum or price_step % price_quantum:
            raise ValueError("inconsistent price tick")
        return cls(pair=pair, price_step=text(price_step), volume_step=text(volume_step),
                   minimum_volume=text(amount(metadata.get("ordermin"))),
                   minimum_cost=text(amount(metadata.get("costmin"), zero_allowed=True)))

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()

    def prepare_buy(self, budget, price_cap, stop, target, limits=RiskLimits()) -> dict[str, str]:
        """Round a buy price/size down, stop up and target down, then recheck."""
        budget = amount(budget)
        if budget > amount(limits.max_position_eurc):
            raise ValueError("budget exceeds risk limit")
        tick, step = amount(self.price_step), amount(self.volume_step)
        def snap(value, rounding):
            return (amount(value) / tick).to_integral_value(rounding=rounding) * tick
        price = snap(price_cap, ROUND_FLOOR)
        stop = snap(stop, ROUND_CEILING)
        target = snap(target, ROUND_FLOOR)
        if not 0 < stop < price < target:
            raise ValueError("rounding invalidates entry/exit prices")
        if (price - stop) / price > amount(limits.max_stop_pct):
            raise ValueError("rounded stop exceeds risk limit")
        if (target - price) / (price - stop) < amount(limits.min_reward_risk):
            raise ValueError("rounded reward/risk is too low")
        volume = (budget / price / step).to_integral_value(rounding=ROUND_FLOOR) * step
        notional = volume * price
        if volume <= 0 or volume < amount(self.minimum_volume):
            raise ValueError("order volume is below exchange minimum")
        minimum_cost = amount(self.minimum_cost, zero_allowed=True)
        if notional < minimum_cost or volume * stop < minimum_cost:
            raise ValueError("entry or planned exit is below exchange minimum cost")
        if notional > budget:
            raise ValueError("rounded order exceeds budget")
        return {"volume": text(volume), "price": text(price), "stop": text(stop),
                "target": text(target), "notional": text(notional)}
