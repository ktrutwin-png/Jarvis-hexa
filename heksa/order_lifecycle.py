"""Simulation-first order lifecycle for the Android application.

The module provides persistent manual approval, hard risk limits, idempotent
client order identifiers and an emergency stop.  It deliberately does not send
live orders.  A later live executor can consume APPROVED records only after
additional exchange-side checks are implemented.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import threading
from typing import Any, Mapping
import uuid

from .risk import RiskLimits, validate_risk
from .market_config import require_eurc_pair


PENDING_STATES = frozenset({"VALIDATED", "APPROVED"})
FINAL_STATES = frozenset({"SIMULATED", "REJECTED", "CANCELLED", "BLOCKED"})


@dataclass(frozen=True)
class ExecutionLimits:
    """Hard limits that cannot be bypassed by signal-scoring code."""

    max_position_eurc: float = 10.0
    max_pending_orders: int = 3
    max_pending_exposure_eurc: float = 20.0
    max_daily_simulations: int = 8
    max_daily_loss_eurc: float = 5.0
    min_confidence: float = 35.0
    max_slippage_bps: float = 20.0
    estimated_entry_fee_bps: float = 40.0


class OrderLifecycle:
    """Persist and guard reviewable orders before any future live execution."""

    def __init__(
        self,
        database: str | Path,
        limits: ExecutionLimits = ExecutionLimits(),
    ) -> None:
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.limits = limits
        self._lock = threading.RLock()
        self._ensure_schema()

    @staticmethod
    def _now() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _today() -> str:
        return datetime.now().astimezone().date().isoformat()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _ensure_schema(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS orders_eurc (
                    id TEXT PRIMARY KEY,
                    client_order_id TEXT NOT NULL UNIQUE,
                    fingerprint TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    pair TEXT NOT NULL,
                    api_pair TEXT NOT NULL,
                    side TEXT NOT NULL CHECK(side IN ('buy', 'sell')),
                    position_eurc REAL NOT NULL CHECK(position_eurc > 0),
                    volume TEXT NOT NULL,
                    entry REAL NOT NULL CHECK(entry > 0),
                    stop_loss REAL NOT NULL CHECK(stop_loss > 0),
                    take_profit REAL NOT NULL CHECK(take_profit > 0),
                    confidence REAL NOT NULL,
                    state TEXT NOT NULL,
                    approved_at TEXT,
                    simulated_at TEXT,
                    fill_price REAL,
                    fee_eurc REAL,
                    block_reason TEXT,
                    source_json TEXT NOT NULL,
                    result_json TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_orders_eurc_state
                    ON orders_eurc(state, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_orders_eurc_created
                    ON orders_eurc(created_at DESC);

                CREATE TABLE IF NOT EXISTS order_events_eurc (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    event TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    FOREIGN KEY(order_id) REFERENCES orders_eurc(id)
                );

                CREATE TABLE IF NOT EXISTS order_controls_eurc (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            # Retain an already enabled emergency stop when upgrading from EUR.
            legacy_stop = "0"
            if connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='order_controls'"
            ).fetchone():
                legacy = connection.execute(
                    "SELECT value FROM order_controls WHERE key='emergency_stop'"
                ).fetchone()
                if legacy and legacy["value"] == "1":
                    legacy_stop = "1"
            connection.execute(
                """
                INSERT OR IGNORE INTO order_controls_eurc(key, value, updated_at)
                VALUES ('emergency_stop', ?, ?)
                """,
                (legacy_stop, self._now()),
            )

    @staticmethod
    def _signal_side(signal_name: str) -> str:
        normalized = signal_name.strip().upper()
        if normalized == "BUY_CANDIDATE":
            return "buy"
        if normalized == "SELL_CANDIDATE":
            return "sell"
        raise ValueError("proposal does not contain an actionable signal")

    def _proposal_data(self, proposal: Mapping[str, Any]) -> dict[str, Any]:
        if str(proposal.get("status") or "").upper() != "PROPOSAL":
            raise ValueError("only actionable PROPOSAL records can enter the lifecycle")
        if not bool(proposal.get("requires_user_approval", True)):
            raise ValueError("proposal is not marked for user approval")

        signal = proposal.get("signal")
        if not isinstance(signal, Mapping):
            raise ValueError("proposal signal is missing")

        pair = require_eurc_pair(str(proposal.get("pair") or ""))
        api_pair = require_eurc_pair(str(proposal.get("api_pair") or pair))
        if not pair or not api_pair:
            raise ValueError("proposal pair is missing")

        side = self._signal_side(str(signal.get("signal") or ""))
        position_eurc = float(proposal.get("position_eurc") or 0.0)
        entry = float(signal.get("last_price") or 0.0)
        stop_loss = float(signal.get("stop_loss") or 0.0)
        take_profit = float(signal.get("take_profit") or 0.0)
        confidence = float(signal.get("confidence") or 0.0)

        if not math.isfinite(confidence) or not self.limits.min_confidence <= confidence <= 100:
            raise ValueError("signal confidence is below the hard minimum")
        if position_eurc > self.limits.max_position_eurc:
            raise ValueError("position exceeds the hard EURC limit")

        validate_risk(
            position_eurc=position_eurc,
            entry=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            limits=RiskLimits(max_position_eurc=self.limits.max_position_eurc),
        )

        execution = proposal.get("execution")
        slippage_bps = 0.0
        if isinstance(execution, Mapping):
            slippage_bps = float(execution.get("slippage_bps") or 0.0)
        if not math.isfinite(slippage_bps) or not 0 <= slippage_bps <= self.limits.max_slippage_bps:
            raise ValueError("estimated slippage exceeds the hard limit")

        volume = position_eurc / entry
        if volume <= 0:
            raise ValueError("calculated order volume is invalid")

        return {
            "pair": pair,
            "api_pair": api_pair,
            "side": side,
            "position_eurc": round(position_eurc, 2),
            "volume": format(volume, ".12f").rstrip("0").rstrip("."),
            "entry": entry,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "confidence": confidence,
            "slippage_bps": slippage_bps,
        }

    def _fingerprint(self, data: Mapping[str, Any]) -> str:
        payload = "|".join(
            (
                self._today(),
                str(data["pair"]),
                str(data["side"]),
                f"{float(data['position_eurc']):.2f}",
                f"{float(data['entry']):.12g}",
                f"{float(data['stop_loss']):.12g}",
                f"{float(data['take_profit']):.12g}",
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        for key in ("source_json", "result_json"):
            raw = item.get(key)
            if raw:
                try:
                    item[key.removesuffix("_json")] = json.loads(raw)
                except json.JSONDecodeError:
                    item[key.removesuffix("_json")] = None
            item.pop(key, None)
        return item

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        order_id: str,
        event: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO order_events_eurc(order_id, created_at, event, details_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                order_id,
                OrderLifecycle._now(),
                event,
                json.dumps(dict(details or {}), ensure_ascii=False, sort_keys=True),
            ),
        )

    @staticmethod
    def _control_value(connection: sqlite3.Connection, key: str) -> str | None:
        row = connection.execute(
            "SELECT value FROM order_controls_eurc WHERE key = ?",
            (key,),
        ).fetchone()
        return str(row["value"]) if row is not None else None

    @staticmethod
    def _set_control(
        connection: sqlite3.Connection,
        key: str,
        value: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO order_controls_eurc(key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, OrderLifecycle._now()),
        )

    def _emergency_stop_in(self, connection: sqlite3.Connection) -> bool:
        return self._control_value(connection, "emergency_stop") == "1"

    def emergency_stop_enabled(self) -> bool:
        with self._lock, self._connect() as connection:
            return self._emergency_stop_in(connection)

    def _daily_realized_pnl_in(self, connection: sqlite3.Connection) -> float:
        raw = self._control_value(connection, f"realized_pnl:{self._today()}")
        try:
            value = float(raw or 0.0)
        except ValueError:
            raise PermissionError("daily P&L data is invalid") from None
        if not math.isfinite(value):
            raise PermissionError("daily P&L data is invalid")
        return value

    def record_realized_pnl(self, pnl_delta_eurc: float) -> float:
        """Record realized P&L for the daily-loss circuit breaker."""
        delta = float(pnl_delta_eurc)
        if not math.isfinite(delta):
            raise ValueError("realized P&L must be finite")
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            value = self._daily_realized_pnl_in(connection) + delta
            self._set_control(
                connection,
                f"realized_pnl:{self._today()}",
                f"{value:.8f}",
            )
            connection.commit()
            return round(value, 8)

    def _assert_circuit_breakers(self, connection: sqlite3.Connection) -> None:
        if self._emergency_stop_in(connection):
            raise PermissionError("emergency stop is active")
        if self._daily_realized_pnl_in(connection) <= -abs(
            self.limits.max_daily_loss_eurc
        ):
            raise PermissionError("daily loss limit is active")

    def _assert_capacity(
        self,
        connection: sqlite3.Connection,
        additional_exposure_eurc: float = 0.0,
        *,
        count_new_order: bool = False,
    ) -> None:
        placeholders = ",".join("?" for _ in PENDING_STATES)
        row = connection.execute(
            f"""
            SELECT COUNT(*) AS pending_count,
                   COALESCE(SUM(position_eurc), 0.0) AS pending_exposure
            FROM orders_eurc
            WHERE state IN ({placeholders})
            """,
            tuple(PENDING_STATES),
        ).fetchone()
        pending_count = int(row["pending_count"] or 0)
        pending_exposure = float(row["pending_exposure"] or 0.0)

        if count_new_order and pending_count >= self.limits.max_pending_orders:
            raise PermissionError("maximum number of pending orders reached")
        if pending_exposure + float(additional_exposure_eurc) > (
            self.limits.max_pending_exposure_eurc + 1e-9
        ):
            raise PermissionError("maximum pending EURC exposure reached")

        day_prefix = self._today() + "%"
        simulations = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM orders_eurc
            WHERE state = 'SIMULATED' AND simulated_at LIKE ?
            """,
            (day_prefix,),
        ).fetchone()
        if int(simulations["count"] or 0) >= self.limits.max_daily_simulations:
            raise PermissionError("daily simulation limit reached")

    def create_from_proposal(self, proposal: Mapping[str, Any]) -> dict[str, Any]:
        """Validate and persist an actionable proposal without approving it."""
        data = self._proposal_data(proposal)
        fingerprint = self._fingerprint(data)
        now = self._now()
        source_json = json.dumps(
            dict(proposal),
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM orders_eurc WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
            if existing is not None:
                connection.commit()
                return self._row_to_dict(existing) or {}

            self._assert_circuit_breakers(connection)
            self._assert_capacity(
                connection,
                data["position_eurc"],
                count_new_order=True,
            )

            order_id = str(uuid.uuid4())
            client_order_id = "nx" + fingerprint[:16]
            connection.execute(
                """
                INSERT INTO orders_eurc(
                    id, client_order_id, fingerprint, created_at, updated_at,
                    pair, api_pair, side, position_eurc, volume, entry,
                    stop_loss, take_profit, confidence, state, source_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'VALIDATED', ?)
                """,
                (
                    order_id,
                    client_order_id,
                    fingerprint,
                    now,
                    now,
                    data["pair"],
                    data["api_pair"],
                    data["side"],
                    data["position_eurc"],
                    data["volume"],
                    data["entry"],
                    data["stop_loss"],
                    data["take_profit"],
                    data["confidence"],
                    source_json,
                ),
            )
            self._event(connection, order_id, "draft_created", data)
            self._event(
                connection,
                order_id,
                "risk_validated",
                {"limits": asdict(self.limits)},
            )
            row = connection.execute(
                "SELECT * FROM orders_eurc WHERE id = ?",
                (order_id,),
            ).fetchone()
            connection.commit()
            return self._row_to_dict(row) or {}

    def approve(self, order_id: str, approved_by: str = "android_user") -> dict[str, Any]:
        """Record explicit user approval.  This still cannot submit a live order."""
        normalized_id = str(order_id).strip()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_circuit_breakers(connection)
            row = connection.execute(
                "SELECT * FROM orders_eurc WHERE id = ?",
                (normalized_id,),
            ).fetchone()
            if row is None:
                raise KeyError("order not found")
            if row["state"] == "APPROVED":
                connection.commit()
                return self._row_to_dict(row) or {}
            if row["state"] != "VALIDATED":
                raise ValueError(f"order cannot be approved from state {row['state']}")

            self._assert_capacity(connection)
            now = self._now()
            connection.execute(
                """
                UPDATE orders_eurc
                SET state = 'APPROVED', approved_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, normalized_id),
            )
            self._event(
                connection,
                normalized_id,
                "manually_approved",
                {"approved_by": approved_by},
            )
            updated = connection.execute(
                "SELECT * FROM orders_eurc WHERE id = ?",
                (normalized_id,),
            ).fetchone()
            connection.commit()
            return self._row_to_dict(updated) or {}

    def simulate(self, order_id: str) -> dict[str, Any]:
        """Simulate an approved entry using conservative slippage and fee estimates."""
        normalized_id = str(order_id).strip()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_circuit_breakers(connection)
            row = connection.execute(
                "SELECT * FROM orders_eurc WHERE id = ?",
                (normalized_id,),
            ).fetchone()
            if row is None:
                raise KeyError("order not found")
            if row["state"] == "SIMULATED":
                connection.commit()
                return self._row_to_dict(row) or {}
            if row["state"] != "APPROVED":
                raise ValueError(f"order cannot be simulated from state {row['state']}")

            self._assert_capacity(connection)
            source = json.loads(row["source_json"])
            execution = source.get("execution") or {}
            observed_slippage = float(execution.get("slippage_bps") or 0.0)
            applied_slippage = min(
                self.limits.max_slippage_bps,
                max(5.0, observed_slippage),
            )
            entry = float(row["entry"])
            direction = 1.0 if row["side"] == "buy" else -1.0
            fill_price = entry * (1.0 + direction * applied_slippage / 10_000.0)
            fee_eurc = float(row["position_eurc"]) * (
                self.limits.estimated_entry_fee_bps / 10_000.0
            )
            result = {
                "mode": "simulation",
                "live_order_submitted": False,
                "client_order_id": row["client_order_id"],
                "applied_slippage_bps": round(applied_slippage, 4),
                "estimated_entry_fee_eurc": round(fee_eurc, 6),
            }
            now = self._now()
            connection.execute(
                """
                UPDATE orders_eurc
                SET state = 'SIMULATED', simulated_at = ?, updated_at = ?,
                    fill_price = ?, fee_eurc = ?, result_json = ?
                WHERE id = ?
                """,
                (
                    now,
                    now,
                    fill_price,
                    fee_eurc,
                    json.dumps(result, ensure_ascii=False, sort_keys=True),
                    normalized_id,
                ),
            )
            self._event(connection, normalized_id, "simulation_filled", result)
            updated = connection.execute(
                "SELECT * FROM orders_eurc WHERE id = ?",
                (normalized_id,),
            ).fetchone()
            connection.commit()
            return self._row_to_dict(updated) or {}

    def approve_and_simulate(
        self,
        proposal: Mapping[str, Any],
        approved_by: str = "android_user",
    ) -> dict[str, Any]:
        """Convenience path used by the Android manual-approval button."""
        order = self.create_from_proposal(proposal)
        if order.get("state") == "VALIDATED":
            order = self.approve(str(order["id"]), approved_by=approved_by)
        if order.get("state") == "APPROVED":
            order = self.simulate(str(order["id"]))
        return order

    def reject(self, order_id: str, reason: str = "rejected_by_user") -> dict[str, Any]:
        normalized_id = str(order_id).strip()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM orders_eurc WHERE id = ?",
                (normalized_id,),
            ).fetchone()
            if row is None:
                raise KeyError("order not found")
            if row["state"] in FINAL_STATES:
                connection.commit()
                return self._row_to_dict(row) or {}
            now = self._now()
            connection.execute(
                """
                UPDATE orders_eurc
                SET state = 'REJECTED', block_reason = ?, updated_at = ?
                WHERE id = ?
                """,
                (reason, now, normalized_id),
            )
            self._event(connection, normalized_id, "rejected", {"reason": reason})
            updated = connection.execute(
                "SELECT * FROM orders_eurc WHERE id = ?",
                (normalized_id,),
            ).fetchone()
            connection.commit()
            return self._row_to_dict(updated) or {}

    def set_emergency_stop(
        self,
        enabled: bool,
        reason: str = "android_emergency_stop",
    ) -> dict[str, Any]:
        """Persist the kill switch and block every pending order when enabled."""
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._set_control(connection, "emergency_stop", "1" if enabled else "0")
            blocked = 0
            if enabled:
                placeholders = ",".join("?" for _ in PENDING_STATES)
                pending = connection.execute(
                    f"SELECT id FROM orders_eurc WHERE state IN ({placeholders})",
                    tuple(PENDING_STATES),
                ).fetchall()
                now = self._now()
                connection.execute(
                    f"""
                    UPDATE orders_eurc
                    SET state = 'BLOCKED', block_reason = ?, updated_at = ?
                    WHERE state IN ({placeholders})
                    """,
                    (reason, now, *tuple(PENDING_STATES)),
                )
                for row in pending:
                    self._event(
                        connection,
                        str(row["id"]),
                        "blocked_by_emergency_stop",
                        {"reason": reason},
                    )
                blocked = len(pending)
            connection.commit()
            return {
                "emergency_stop": bool(enabled),
                "blocked_pending_orders": blocked,
                "reason": reason,
            }

    def get(self, order_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM orders_eurc WHERE id = ?",
                (str(order_id).strip(),),
            ).fetchone()
            return self._row_to_dict(row)

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 100))
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM orders_eurc ORDER BY created_at DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
            return [self._row_to_dict(row) or {} for row in rows]

    def summary(self) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            placeholders = ",".join("?" for _ in PENDING_STATES)
            pending = connection.execute(
                f"""
                SELECT COUNT(*) AS count,
                       COALESCE(SUM(position_eurc), 0.0) AS exposure
                FROM orders_eurc
                WHERE state IN ({placeholders})
                """,
                tuple(PENDING_STATES),
            ).fetchone()
            simulations = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM orders_eurc
                WHERE state = 'SIMULATED' AND simulated_at LIKE ?
                """,
                (self._today() + "%",),
            ).fetchone()
            total = connection.execute(
                "SELECT COUNT(*) AS count FROM orders_eurc"
            ).fetchone()
            return {
                "emergency_stop": self._emergency_stop_in(connection),
                "pending_orders": int(pending["count"] or 0),
                "pending_exposure_eurc": round(float(pending["exposure"] or 0.0), 2),
                "simulations_today": int(simulations["count"] or 0),
                "daily_realized_pnl_eurc": round(
                    self._daily_realized_pnl_in(connection),
                    2,
                ),
                "total_orders": int(total["count"] or 0),
                "limits": asdict(self.limits),
                "live_order_submission_enabled": False,
            }

