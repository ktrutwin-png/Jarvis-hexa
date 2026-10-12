"""Phone-local continuous EURC analysis. No server or order submission."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import sqlite3
import threading

from .journal import SignalJournal
from .trading_runner import build_best_eurc_proposals


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MarketMonitor:
    """One scan at a time; decisions invalidate in-flight results."""

    def __init__(self, data_dir: str | Path, interval: int = 60, ttl: int = 120):
        if not 30 <= interval <= 3600 or not 30 <= ttl <= 900:
            raise ValueError("Invalid scan interval or proposal lifetime")
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.journal = SignalJournal(self.data_dir / "signals.sqlite3")
        self.database = self.data_dir / "monitor.sqlite3"
        self.interval, self.ttl = interval, ttl
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.closed = threading.Event()
        self.worker: threading.Thread | None = None
        self.enabled = False
        self.scanning = False
        self.revision = 0
        with sqlite3.connect(self.database) as db:
            db.execute("CREATE TABLE IF NOT EXISTS snapshot(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)")
            row = db.execute("SELECT payload FROM snapshot WHERE id=1").fetchone()
        self.state = json.loads(row[0]) if row else {
            "last_scan_at": None, "last_success_at": None,
            "last_error": None, "markets_scanned": 0,
        }
        # A recovered proposal must never become actionable without fresh data.
        self.state.update(proposal=None, last_error=None)
        self._persist()

    def _persist(self) -> None:
        with sqlite3.connect(self.database, timeout=10) as db:
            db.execute("INSERT INTO snapshot(id,payload) VALUES(1,?) "
                       "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                       (json.dumps(self.state, ensure_ascii=False, allow_nan=False),))

    def _current(self) -> dict | None:
        proposal = self.state.get("proposal")
        if not proposal or datetime.fromisoformat(proposal["expires_at"]) <= utc_now():
            return None
        if proposal["pair"] in self.journal.rejected_pairs():
            return None
        return proposal

    def snapshot(self) -> dict:
        with self.lock:
            proposal = self._current()
            return deepcopy({
                **self.state, "proposal": proposal,
                "proposals": [proposal] if proposal else [],
                "actionable_candidates": int(proposal is not None),
                "quote_currency": "EURC", "scanning": self.scanning,
                "monitor_enabled": self.enabled, "interval_seconds": self.interval,
                "live_order_submission_enabled": False,
            })

    @staticmethod
    def _terms(proposal: dict) -> tuple:
        signal = proposal.get("signal") or {}
        return (proposal.get("pair"), proposal.get("position_eurc"),
                signal.get("signal"), signal.get("last_price"),
                signal.get("stop_loss"), signal.get("take_profit"),
                proposal.get("estimated_round_trip_cost_bps"))

    def scan_once(self, *, require_enabled: bool = False) -> bool:
        with self.lock:
            if self.scanning or (require_enabled and not self.enabled):
                return False
            revision = self.revision
            self.scanning = True
            self.state["last_scan_at"] = utc_now().isoformat()
        try:
            result = build_best_eurc_proposals(limit=5, journal=self.journal)
            now = utc_now()
            candidate = None
            for item in result.get("proposals", []):
                if item.get("status") != "PROPOSAL":
                    continue
                expires = datetime.fromisoformat(item["analyzed_at"]) + timedelta(seconds=self.ttl)
                if expires > now:
                    candidate = {**item, "expires_at": expires.isoformat()}
                    break
            with self.lock:
                if revision != self.revision:
                    return False
                previous = self._current()
                if candidate and previous and self._terms(candidate) == self._terms(previous):
                    # An unchanged card retains both ID and deadline.
                    candidate = previous
                self.state.update(proposal=candidate, last_success_at=now.isoformat(),
                                  last_error=None, markets_scanned=result.get("markets_scanned", 0))
                self._persist()
            return True
        except Exception as error:
            logging.getLogger(__name__).warning("Scan failed: %s", type(error).__name__)
            with self.lock:
                if revision == self.revision:
                    self.state.update(proposal=None, last_error="Brak świeżych danych. Ponawiam połączenie.")
                    self._persist()
            return False
        finally:
            with self.lock:
                self.scanning = False

    def reject(self, proposal_id: str) -> bool:
        with self.lock:
            proposal = self._current()
            if proposal is None or proposal.get("proposal_id") != proposal_id:
                return False
            self.journal.reject_proposal(proposal)
            self._invalidate()
            return True

    def _invalidate(self) -> None:
        self.state["proposal"] = None
        self.revision += 1
        self._persist()
        self.wake.set()

    def invalidate(self) -> None:
        with self.lock:
            self._invalidate()

    def _run(self) -> None:
        while not self.closed.is_set():
            self.wake.clear()
            if self.enabled:
                try:
                    self.scan_once(require_enabled=True)
                except Exception:
                    logging.getLogger(__name__).exception("Monitor storage failure")
            self.wake.wait(self.interval if self.enabled else None)

    def start(self) -> None:
        with self.lock:
            self.enabled = True
            self.wake.set()
            if self.worker is None or not self.worker.is_alive():
                self.worker = threading.Thread(target=self._run, name="eurc-monitor", daemon=True)
                self.worker.start()

    def stop(self) -> None:
        with self.lock:
            self.enabled = False
            self._invalidate()

    def close(self) -> None:
        self.stop()
        self.closed.set()
        self.wake.set()
