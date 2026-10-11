"""Persistent EUR signal journal and performance summaries."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class SignalJournal:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS signals (
                    id TEXT PRIMARY KEY,
                    created TEXT NOT NULL,
                    pair TEXT NOT NULL,
                    status TEXT NOT NULL,
                    side TEXT,
                    entry_eur REAL,
                    position_eur REAL,
                    confidence REAL,
                    market_score REAL,
                    final_score REAL,
                    stop_loss_eur REAL,
                    take_profit_eur REAL,
                    payload_json TEXT NOT NULL
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS outcomes (
                    signal_id TEXT PRIMARY KEY,
                    closed TEXT NOT NULL,
                    exit_eur REAL NOT NULL,
                    pnl_eur REAL NOT NULL,
                    result TEXT NOT NULL,
                    FOREIGN KEY(signal_id) REFERENCES signals(id)
                )"""
            )

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def record(self, proposal: dict) -> str:
        signal_id = uuid4().hex
        signal = proposal.get("signal") or {}
        opportunity = proposal.get("opportunity") or {}
        signal_name = str(signal.get("signal") or "")
        side = (
            "buy"
            if signal_name == "BUY_CANDIDATE"
            else "sell"
            if signal_name == "SELL_CANDIDATE"
            else None
        )

        values = (
            signal_id,
            datetime.now(timezone.utc).isoformat(),
            str(proposal.get("pair") or ""),
            str(proposal.get("status") or ""),
            side,
            _as_float(signal.get("last_price")),
            _as_float(proposal.get("position_eur")),
            _as_float(signal.get("confidence")),
            _as_float(opportunity.get("opportunity_score")),
            _as_float(proposal.get("final_score")),
            _as_float(signal.get("stop_loss")),
            _as_float(signal.get("take_profit")),
            json.dumps(proposal, ensure_ascii=False, separators=(",", ":")),
        )

        with self._connect() as db:
            db.execute(
                """INSERT INTO signals (
                    id, created, pair, status, side, entry_eur, position_eur,
                    confidence, market_score, final_score, stop_loss_eur,
                    take_profit_eur, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                values,
            )
        return signal_id

    def recent(self, limit: int = 20) -> list[dict]:
        safe_limit = max(1, min(int(limit), 200))
        with self._connect() as db:
            rows = db.execute(
                """SELECT s.*, o.closed, o.exit_eur, o.pnl_eur, o.result
                   FROM signals s
                   LEFT JOIN outcomes o ON o.signal_id = s.id
                   ORDER BY s.created DESC
                   LIMIT ?""",
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def close(self, signal_id: str, exit_eur: float) -> dict:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM signals WHERE id=?",
                (signal_id,),
            ).fetchone()
            if row is None:
                raise ValueError("unknown signal id")

            if db.execute(
                "SELECT 1 FROM outcomes WHERE signal_id=?",
                (signal_id,),
            ).fetchone():
                raise ValueError("signal already closed")

            entry = float(row["entry_eur"] or 0.0)
            position = float(row["position_eur"] or 0.0)
            side = row["side"]
            if entry <= 0 or position <= 0 or side not in {"buy", "sell"}:
                raise ValueError("signal is not an actionable position")

            move = (float(exit_eur) - entry) / entry
            if side == "sell":
                move = -move

            pnl_eur = position * move
            result = "win" if pnl_eur > 0 else "loss" if pnl_eur < 0 else "flat"
            closed = datetime.now(timezone.utc).isoformat()

            db.execute(
                """INSERT INTO outcomes
                   (signal_id, closed, exit_eur, pnl_eur, result)
                   VALUES (?, ?, ?, ?, ?)""",
                (signal_id, closed, float(exit_eur), pnl_eur, result),
            )

        return {
            "signal_id": signal_id,
            "exit_eur": float(exit_eur),
            "pnl_eur": pnl_eur,
            "result": result,
        }

    def pair_performance(self, pair: str, side: str | None = None) -> dict:
        """Return conservative historical quality stats for one market/side.

        A small prior keeps early outcomes from dominating ranking decisions.
        """
        normalized_pair = pair.strip().upper()
        params: list[object] = [normalized_pair]
        where = "WHERE s.pair=? AND o.signal_id IS NOT NULL"

        if side:
            where += " AND s.side=?"
            params.append(side.strip().lower())

        with self._connect() as db:
            row = db.execute(
                f"""SELECT
                    COUNT(*) AS closed_count,
                    COALESCE(SUM(CASE WHEN o.result='win' THEN 1 ELSE 0 END), 0) AS wins,
                    COALESCE(SUM(CASE WHEN o.result='loss' THEN 1 ELSE 0 END), 0) AS losses,
                    COALESCE(SUM(o.pnl_eur), 0.0) AS pnl_eur,
                    COALESCE(AVG(
                        CASE
                            WHEN s.position_eur > 0
                            THEN (o.pnl_eur / s.position_eur) * 100.0
                            ELSE NULL
                        END
                    ), 0.0) AS avg_return_pct
                   FROM signals s
                   JOIN outcomes o ON o.signal_id = s.id
                   {where}""",
                params,
            ).fetchone()

        closed = int(row["closed_count"])
        wins = int(row["wins"])
        losses = int(row["losses"])
        avg_return_pct = float(row["avg_return_pct"])

        # Beta(3,3) prior: early streaks are intentionally damped.
        bayesian_win_rate = (wins + 3.0) / (closed + 6.0)

        # Historical data must refine the live score, never overwhelm it.
        if closed < 3:
            multiplier = 1.0
        else:
            win_component = (bayesian_win_rate - 0.5) * 0.40
            return_component = max(-5.0, min(5.0, avg_return_pct)) * 0.02
            multiplier = max(0.80, min(1.20, 1.0 + win_component + return_component))

        return {
            "pair": normalized_pair,
            "side": side.strip().lower() if side else None,
            "closed_count": closed,
            "wins": wins,
            "losses": losses,
            "bayesian_win_rate_pct": bayesian_win_rate * 100.0,
            "avg_return_pct": avg_return_pct,
            "pnl_eur": float(row["pnl_eur"]),
            "ranking_multiplier": multiplier,
        }

    def summary(self) -> dict:
        with self._connect() as db:
            row = db.execute(
                """SELECT
                    COUNT(*) AS closed_count,
                    COALESCE(SUM(pnl_eur), 0.0) AS pnl_eur,
                    COALESCE(SUM(CASE WHEN result='win' THEN 1 ELSE 0 END), 0) AS wins,
                    COALESCE(SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END), 0) AS losses
                   FROM outcomes"""
            ).fetchone()

        closed = int(row["closed_count"])
        wins = int(row["wins"])
        return {
            "closed_count": closed,
            "wins": wins,
            "losses": int(row["losses"]),
            "win_rate_pct": (wins / closed * 100.0) if closed else 0.0,
            "pnl_eur": float(row["pnl_eur"]),
        }


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
