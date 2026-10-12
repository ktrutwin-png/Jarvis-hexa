"""Durable, single-account entry attempts for a future live executor.

No method submits an order. A new claim is only a duplicate-prevention gate:
the executor still needs market precision/minimum checks and exit protection.
Once a claim is committed, neither a timeout nor an empty exchange lookup may
authorize a second submission. Completed buys remain blocked pending a future
position manager; this module never treats an entry fill as realized profit.
"""
from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sqlite3
import uuid

from .market_config import base_symbol, require_eurc_pair
from .trade_intent import recheck_approved_intent


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decimal(value, *, positive: bool = False) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("invalid exchange amount") from None
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise ValueError("invalid exchange amount")
    return result


class EntryJournal:
    def __init__(self, database: str | Path):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS entry_attempts (
                    client_order_id TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL UNIQUE,
                    fingerprint TEXT NOT NULL,
                    intent_json TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN (
                        'SUBMITTING', 'UNKNOWN', 'ACKNOWLEDGED', 'OPEN',
                        'PARTIAL', 'ENTRY_COMPLETE', 'NO_FILL')),
                    exchange_order_id TEXT,
                    exchange_status TEXT,
                    filled_volume TEXT NOT NULL DEFAULT '0',
                    cost TEXT NOT NULL DEFAULT '0',
                    reported_fee TEXT NOT NULL DEFAULT '0',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_issue TEXT
                );
                CREATE TABLE IF NOT EXISTS entry_attempt_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_order_id TEXT NOT NULL REFERENCES entry_attempts(client_order_id),
                    created_at TEXT NOT NULL,
                    event TEXT NOT NULL
                );
            """)

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _view(row, *, new_attempt: bool = False) -> dict:
        result = dict(row)
        result["intent"] = json.loads(result.pop("intent_json"))
        result["new_attempt"] = new_attempt
        return result

    @staticmethod
    def _row(db, client_order_id):
        row = db.execute("SELECT * FROM entry_attempts WHERE client_order_id=?",
                         (client_order_id,)).fetchone()
        if row is None:
            raise KeyError("entry attempt not found")
        return row

    @staticmethod
    def _event(db, client_order_id, event):
        db.execute("INSERT INTO entry_attempt_events(client_order_id,created_at,event) VALUES(?,?,?)",
                   (client_order_id, _now(), event))

    def claim(self, proposal: Mapping, approved_fingerprint: str, **preflight) -> dict:
        """Commit one attempt before any network write, even across processes.

        A duplicate returns the original attempt with new_attempt=False, including
        after expiry/restart. There is intentionally no reset/retry-send method.
        This database belongs to one account; do not switch accounts while it has
        active attempts. Never persist API keys or HTTP responses here.
        """
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM entry_attempts WHERE proposal_id=?",
                                  (proposal.get("proposal_id"),)).fetchone()
            if existing is not None:
                if existing["fingerprint"] != approved_fingerprint:
                    raise PermissionError("approval differs from the original attempt")
                return self._view(existing)
            if db.execute("SELECT 1 FROM entry_attempts WHERE state!='NO_FILL' OR last_issue IS NOT NULL LIMIT 1").fetchone():
                raise PermissionError("previous entry or acquired position must be reconciled first")
            intent = recheck_approved_intent(proposal, approved_fingerprint, **preflight)
            client_order_id, now = str(uuid.uuid4()), _now()
            db.execute("""INSERT INTO entry_attempts
                (client_order_id,proposal_id,fingerprint,intent_json,state,created_at,updated_at)
                VALUES(?,?,?,?,'SUBMITTING',?,?)""",
                (client_order_id, intent.proposal_id, intent.fingerprint,
                 json.dumps(intent.to_dict(), sort_keys=True, allow_nan=False), now, now))
            self._event(db, client_order_id, "attempt_committed_before_send")
            return self._view(self._row(db, client_order_id), new_attempt=True)

    def get(self, client_order_id: str) -> dict:
        with self._connection() as db:
            return self._view(self._row(db, client_order_id))

    def active(self) -> list[dict]:
        """Read on startup; SUBMITTING also means 'outcome unknown', never resend."""
        with self._connection() as db:
            return [self._view(row) for row in db.execute(
                "SELECT * FROM entry_attempts WHERE state!='NO_FILL' OR last_issue IS NOT NULL ORDER BY created_at")]

    def note_uncertain(self, client_order_id: str, issue: str = "response_missing") -> dict:
        # Callers supply a fixed issue code, never an exception containing secrets.
        if issue not in {"response_missing", "invalid_response", "lookup_failed",
                         "not_found", "conflicting_orders", "invalid_order"}:
            raise ValueError("unknown issue code")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, client_order_id)
            # A late timeout cannot erase a reconciled fill or final cancellation.
            state = "UNKNOWN" if row["state"] in {"SUBMITTING", "UNKNOWN"} else row["state"]
            db.execute("UPDATE entry_attempts SET state=?,last_issue=?,updated_at=? WHERE client_order_id=?",
                       (state, issue, _now(), client_order_id))
            self._event(db, client_order_id, issue)
            return self._view(self._row(db, client_order_id))

    def record_response(self, client_order_id: str, response: Mapping) -> dict:
        """Acknowledgement is not a fill. Ambiguous replies require lookup."""
        result = response.get("result") if isinstance(response, Mapping) else None
        ids = result.get("txid") if isinstance(result, Mapping) else None
        if (not isinstance(response, Mapping) or response.get("error") != []
                or not isinstance(ids, list) or len(ids) != 1
                or not isinstance(ids[0], str) or not ids[0].strip()):
            return self.note_uncertain(client_order_id, "invalid_response")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, client_order_id)
            if row["exchange_order_id"] and row["exchange_order_id"] != ids[0]:
                db.execute("UPDATE entry_attempts SET last_issue='conflicting_orders',updated_at=? WHERE client_order_id=?",
                           (_now(), client_order_id))
                self._event(db, client_order_id, "conflicting_orders")
                return self._view(self._row(db, client_order_id))
            state = "ACKNOWLEDGED" if row["state"] in {"SUBMITTING", "UNKNOWN"} else row["state"]
            db.execute("""UPDATE entry_attempts SET state=?,exchange_order_id=?,updated_at=?
                WHERE client_order_id=?""", (state, ids[0], _now(), client_order_id))
            self._event(db, client_order_id, "exchange_acknowledged_not_filled")
            return self._view(self._row(db, client_order_id))

    def reconcile(self, client_order_id: str, client) -> dict:
        """Read open AND closed orders; absence never permits a second send."""
        self.get(client_order_id)
        try:
            orders = client.orders_by_client_id(client_order_id)
        except Exception:
            return self.note_uncertain(client_order_id, "lookup_failed")
        if not isinstance(orders, Mapping):
            return self.note_uncertain(client_order_id, "invalid_order")
        if not orders:
            return self.note_uncertain(client_order_id, "not_found")
        if len(orders) != 1:
            return self.note_uncertain(client_order_id, "conflicting_orders")
        exchange_id, order = next(iter(orders.items()))
        try:
            return self._apply_order(client_order_id, exchange_id, order)
        except (ValueError, TypeError, KeyError, InvalidOperation):
            return self.note_uncertain(client_order_id, "invalid_order")

    def _apply_order(self, client_order_id, exchange_id, order) -> dict:
        if not isinstance(order, Mapping) or order.get("cl_ord_id") != client_order_id:
            raise ValueError("client order identity mismatch")
        if not isinstance(exchange_id, str) or not exchange_id.strip():
            raise ValueError("exchange order identity missing")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, client_order_id)
            intent = json.loads(row["intent_json"])
            if row["exchange_order_id"] and row["exchange_order_id"] != exchange_id:
                raise ValueError("exchange order identity mismatch")
            descr = order.get("descr") or {}
            if not isinstance(descr, Mapping):
                raise ValueError("invalid order description")
            pair = require_eurc_pair(str(descr.get("pair") or ""))
            if (base_symbol(pair) != base_symbol(intent["pair"])
                    or descr.get("type") != "buy" or descr.get("ordertype") != "limit"
                    or str(descr.get("leverage", "none")) not in {"none", "0:1", "0"}):
                raise ValueError("unexpected order terms")
            volume = _decimal(order.get("vol"), positive=True)
            filled = _decimal(order.get("vol_exec"))
            cost, fee = _decimal(order.get("cost")), _decimal(order.get("fee"))
            limit_price = _decimal(descr.get("price"), positive=True)
            if (filled > volume or limit_price > _decimal(intent["entry_limit_eurc"])
                    or limit_price * volume > _decimal(intent["position_eurc"])
                    or cost > limit_price * filled
                    or (filled > 0 and cost == 0) or (filled == 0 and cost != 0)):
                raise ValueError("unexpected order amounts")
            status = order.get("status")
            if status not in {"pending", "open", "closed", "canceled", "expired"}:
                raise ValueError("unknown exchange state")
            if status == "closed" and filled != volume:
                raise ValueError("incomplete closed order")
            terminal = status in {"closed", "canceled", "expired"}
            if filled < _decimal(row["filled_volume"]) or cost < _decimal(row["cost"]):
                return self._view(row)  # Out-of-order snapshot; keep proven fills.
            if row["state"] in {"ENTRY_COMPLETE", "NO_FILL"} and not terminal:
                return self._view(row)
            if terminal:
                state = "ENTRY_COMPLETE" if filled else "NO_FILL"
            else:
                state = "PARTIAL" if filled else "OPEN"
            db.execute("""UPDATE entry_attempts SET state=?,exchange_order_id=?,exchange_status=?,
                filled_volume=?,cost=?,reported_fee=?,last_issue=NULL,updated_at=? WHERE client_order_id=?""",
                (state, exchange_id, status, str(filled), str(cost), str(fee), _now(), client_order_id))
            self._event(db, client_order_id, "exchange_status_" + status)
            return self._view(self._row(db, client_order_id))
