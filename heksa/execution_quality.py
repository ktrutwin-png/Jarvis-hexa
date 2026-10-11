"""Execution-quality analysis from Kraken aggregated order-book levels.

This module estimates whether a proposed EUR position is realistically
executable before it is surfaced as an actionable candidate.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .kraken_market import fetch_pretrade


@dataclass(frozen=True)
class ExecutionQuality:
    side: str
    best_price: float
    average_price: float
    slippage_bps: float
    available_depth_eur: float
    depth_multiple: float
    book_imbalance: float
    executable: bool

    def to_dict(self) -> dict:
        return asdict(self)


def _levels(raw_levels) -> list[tuple[float, float]]:
    parsed: list[tuple[float, float]] = []
    for level in raw_levels or []:
        try:
            price = float(level["price"])
            qty = float(level["qty"])
        except (KeyError, TypeError, ValueError):
            continue
        if price > 0 and qty > 0:
            parsed.append((price, qty))
    return parsed


def _book_imbalance(
    bids: list[tuple[float, float]],
    asks: list[tuple[float, float]],
) -> float:
    bid_value = sum(price * qty for price, qty in bids)
    ask_value = sum(price * qty for price, qty in asks)
    total = bid_value + ask_value
    return (bid_value - ask_value) / total if total > 0 else 0.0


def _simulate_buy(
    asks: list[tuple[float, float]],
    notional_eur: float,
) -> tuple[float, float, float]:
    if not asks:
        raise ValueError("empty ask book")

    remaining_eur = notional_eur
    base_acquired = 0.0
    spent_eur = 0.0

    for price, qty in asks:
        level_value = price * qty
        take_value = min(remaining_eur, level_value)
        base_acquired += take_value / price
        spent_eur += take_value
        remaining_eur -= take_value
        if remaining_eur <= 1e-9:
            break

    if remaining_eur > 1e-6 or base_acquired <= 0:
        raise ValueError("insufficient ask depth")

    average = spent_eur / base_acquired
    best = asks[0][0]
    slippage_bps = max(0.0, (average / best - 1.0) * 10_000.0)
    return best, average, slippage_bps


def _simulate_sell(
    bids: list[tuple[float, float]],
    notional_eur: float,
) -> tuple[float, float, float]:
    if not bids:
        raise ValueError("empty bid book")

    best = bids[0][0]
    base_to_sell = notional_eur / best
    remaining_base = base_to_sell
    proceeds_eur = 0.0
    sold_base = 0.0

    for price, qty in bids:
        take_qty = min(remaining_base, qty)
        proceeds_eur += take_qty * price
        sold_base += take_qty
        remaining_base -= take_qty
        if remaining_base <= 1e-12:
            break

    if remaining_base > 1e-9 or sold_base <= 0:
        raise ValueError("insufficient bid depth")

    average = proceeds_eur / sold_base
    slippage_bps = max(0.0, (1.0 - average / best) * 10_000.0)
    return best, average, slippage_bps


def assess_execution(
    symbol: str,
    side: str,
    position_eur: float,
    max_slippage_bps: float = 20.0,
    min_depth_multiple: float = 8.0,
) -> ExecutionQuality:
    normalized_side = side.strip().lower()
    if normalized_side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if position_eur <= 0:
        raise ValueError("position_eur must be positive")

    book = fetch_pretrade(symbol)
    bids = _levels(book.get("bids"))
    asks = _levels(book.get("asks"))
    relevant = asks if normalized_side == "buy" else bids

    available_depth_eur = sum(price * qty for price, qty in relevant)
    depth_multiple = available_depth_eur / position_eur if position_eur > 0 else 0.0

    if normalized_side == "buy":
        best, average, slippage = _simulate_buy(asks, position_eur)
    else:
        best, average, slippage = _simulate_sell(bids, position_eur)

    executable = (
        slippage <= max_slippage_bps
        and depth_multiple >= min_depth_multiple
    )

    return ExecutionQuality(
        side=normalized_side,
        best_price=best,
        average_price=average,
        slippage_bps=slippage,
        available_depth_eur=available_depth_eur,
        depth_multiple=depth_multiple,
        book_imbalance=_book_imbalance(bids, asks),
        executable=executable,
    )
