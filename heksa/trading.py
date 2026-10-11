"""Trading proposal pipeline for Heksa.

Builds reviewable proposals. It never submits live orders.
"""
from __future__ import annotations

from dataclasses import dataclass

from .kraken import KrakenClient, OrderProposal
from .market_analysis import MarketSignal, analyze_prices


@dataclass(frozen=True)
class TradeProposal:
    pair: str
    side: str
    volume: str
    signal: MarketSignal
    validated_order: OrderProposal


class TradingProposalService:
    def __init__(self, kraken: KrakenClient | None = None) -> None:
        self.kraken = kraken or KrakenClient()

    def build(
        self,
        pair: str,
        volume: str,
        prices: list[float],
    ) -> TradeProposal | None:
        signal = analyze_prices(prices)

        if signal.signal == "WAIT":
            return None

        side = "buy" if signal.signal == "BUY_CANDIDATE" else "sell"
        validated = self.kraken.prepare_order(pair, side, volume)

        return TradeProposal(
            pair=pair.strip().upper(),
            side=side,
            volume=volume.strip(),
            signal=signal,
            validated_order=validated,
        )
