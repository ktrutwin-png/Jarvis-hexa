"""Kraken integration for Heksa.

This module deliberately validates orders only. It never submits a live order.
API credentials may be injected at runtime (for example from Android secure
storage) or read from environment variables. They must never be committed.
"""
from __future__ import annotations

import os
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import krakenex
from .market_config import require_eurc_pair


REQUEST_TIMEOUT_SECONDS = 15


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
        response: dict[str, Any] = self.api.query_private(
            "Balance", timeout=REQUEST_TIMEOUT_SECONDS
        )
        errors = response.get("error") or []
        if errors:
            raise RuntimeError("; ".join(errors))
        return response.get("result", {})

    def orders_by_client_id(self, client_order_id: str) -> dict[str, dict]:
        """Read this app's UUID-tagged open and closed orders; never resubmit.

        A filled order can disappear from OpenOrders before a timed-out caller
        reads it. ClosedOrders must therefore also be queried. Unexpected extra
        history/pagination is ambiguous, not evidence that no order exists.
        """
        if str(uuid.UUID(client_order_id)) != client_order_id:
            raise ValueError("expected a canonical client order UUID")
        orders = {}
        for endpoint, key in (("OpenOrders", "open"), ("ClosedOrders", "closed")):
            response = self.api.query_private(
                endpoint, {"cl_ord_id": client_order_id, "trades": True},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if not isinstance(response, Mapping) or response.get("error") != []:
                raise RuntimeError("Order status lookup failed")
            result = response.get("result")
            found = result.get(key) if isinstance(result, Mapping) else None
            if not isinstance(found, Mapping):
                raise RuntimeError("Invalid order status response")
            if key == "closed":
                count = result.get("count")
                if isinstance(count, bool) or not isinstance(count, int) or count != len(found):
                    raise RuntimeError("Incomplete closed-order lookup")
                if (result.get("cursor") or {}).get("next"):
                    raise RuntimeError("Incomplete closed-order lookup")
            for order_id, order in found.items():
                if not isinstance(order, Mapping) or order.get("cl_ord_id") != client_order_id:
                    raise RuntimeError("Order identity mismatch")
                # A close between these two reads appears in both collections.
                orders[order_id] = dict(order)
        return orders

    def prepare_order(self, pair: str, side: str, volume: str) -> OrderProposal:
        """Validate an order with Kraken without submitting it."""
        pair = require_eurc_pair(pair)
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
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        errors = response.get("error") or []
        if errors:
            raise RuntimeError("; ".join(errors))

        return OrderProposal(pair=pair, side=side, volume=volume)

    def _query_records(self, endpoint: str, parameter: str, ids: list[str], **options) -> dict:
        """Read exact IDs in Kraken's batches of at most 20; never accept gaps."""
        if (not isinstance(ids, list) or len(ids) > 4000
                or any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,128}", value)
                       for value in ids) or len(set(ids)) != len(ids)):
            raise ValueError("Invalid exchange record IDs")
        records = {}
        for offset in range(0, len(ids), 20):
            batch = ids[offset:offset + 20]
            response = self.api.query_private(
                endpoint, {parameter: ",".join(batch), **options},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            found = response.get("result") if isinstance(response, Mapping) else None
            if (not isinstance(response, Mapping) or response.get("error") != []
                    or not isinstance(found, Mapping) or set(found) != set(batch)
                    or any(not isinstance(value, Mapping) for value in found.values())):
                raise RuntimeError("Incomplete exchange settlement lookup")
            records.update(found)
        return records

    def settlement_for_order(self, order_id: str) -> dict:
        """Read fills and their actual ledger fees, without any trading call.

        Trade/order `fee` is a quote-currency value, not proof of the asset
        deducted. QueryTrades(ledgers=True) links the actual balance movements.
        Missing/delayed records fail the whole lookup and must be retried as reads.
        """
        order = self._query_records("QueryOrders", "txid", [order_id], trades=True)[order_id]
        trades = self._query_records("QueryTrades", "txid", order.get("trades", []), ledgers=True)
        ledger_ids = []
        for trade in trades.values():
            ids = trade.get("ledgers")
            if not isinstance(ids, list) or not ids:
                raise RuntimeError("Missing settlement ledger links")
            ledger_ids.extend(ids)
        ledgers = self._query_records("QueryLedgers", "id", ledger_ids)
        return {"order": order, "trades": trades, "ledgers": ledgers}
