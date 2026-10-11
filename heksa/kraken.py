"""Kraken integration for Heksa.

This module deliberately validates orders only. It never submits a live order.
API credentials may be injected at runtime (for example from Android secure
storage) or read from environment variables. They must never be committed.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import krakenex


@dataclass(frozen=True)
class OrderProposal:
    pair: str
    side: str
    volume: str


class KrakenClient:
    def __init__(
        self,
        key: str | None = None,
        secret: str | None = None,
    ) -> None:
        resolved_key = (key or os.getenv("KRAKEN_API_KEY") or "").strip()
        resolved_secret = (
            secret or os.getenv("KRAKEN_PRIVATE_KEY") or ""
        ).strip()

        if not resolved_key or not resolved_secret:
            raise RuntimeError("Missing Kraken API credentials")

        self.api = krakenex.API(key=resolved_key, secret=resolved_secret)

    def balances(self) -> dict[str, str]:
        response: dict[str, Any] = self.api.query_private("Balance")
        errors = response.get("error") or []
        if errors:
            raise RuntimeError("; ".join(errors))
        return response.get("result", {})

    def prepare_order(self, pair: str, side: str, volume: str) -> OrderProposal:
        """Validate an order with Kraken without submitting it."""
        pair = pair.strip().upper()
        side = side.strip().lower()
        volume = volume.strip()
        if side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if not pair or not volume:
            raise ValueError("pair and volume are required")

        response: dict[str, Any] = self.api.query_private(
            "AddOrder",
            {
                "pair": pair,
                "type": side,
                "ordertype": "market",
                "volume": volume,
                "validate": True,
            },
        )
        errors = response.get("error") or []
        if errors:
            raise RuntimeError("; ".join(errors))

        return OrderProposal(pair=pair, side=side, volume=volume)
