"""Read-only exchange reconciliation for a future spot-position executor.

This is accounting, not authority to place/retry an order or release an entry
lock. Only explicitly linked app orders contribute; pre-existing wallet holdings
and SignalJournal's estimated outcomes never become this position's inventory.
All amounts are decimal strings. Actual fees come from ledger entries, not the
quote-value estimate in an order/trade's `fee` field.
"""
from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation, localcontext
import json
import uuid

from .entry_journal import EntryJournal, _now
from .market_config import base_symbol


TERMINAL = {"closed", "canceled", "expired"}


def _amount(value, *, signed=False, positive=False) -> Decimal:
    # Bound precision/exponents before arithmetic, and reject floats/bools.
    if not isinstance(value, (str, int, Decimal)) or isinstance(value, bool):
        raise ValueError("Invalid accounting amount")
    if len(str(value)) > 80:
        raise ValueError("Invalid accounting amount")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError):
        raise ValueError("Invalid accounting amount") from None
    if (not result.is_finite() or result.copy_abs() > Decimal("1e20")
            or result.as_tuple().exponent < -24
            or (not signed and result < 0) or (positive and result <= 0)):
        raise ValueError("Invalid accounting amount")
    return result


def _text(value: Decimal) -> str:
    return "0" if value == 0 else format(value.normalize(), "f")


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _ids(value) -> list[str]:
    if (not isinstance(value, list) or len(value) > 4000
            or any(not isinstance(item, str) or not item or len(item) > 128 for item in value)
            or len(set(value)) != len(value)):
        raise ValueError("Invalid accounting record IDs")
    return value


def _normalize_settlement(binding, intent, report):
    """Require a complete order snapshot and both asset ledgers for every fill."""
    if not isinstance(report, Mapping):
        raise ValueError("Missing settlement")
    order, trades, ledgers = (report.get(key) for key in ("order", "trades", "ledgers"))
    if not all(isinstance(item, Mapping) for item in (order, trades, ledgers)):
        raise ValueError("Incomplete settlement")
    descr = order.get("descr")
    if (not isinstance(descr, Mapping) or order.get("cl_ord_id") != binding["expected_client_id"]
            or descr.get("type") != binding["side"]
            or base_symbol(str(descr.get("pair", ""))) != base_symbol(intent["pair"])
            or str(descr.get("leverage", "none")) not in {"none", "0", "0:1"}):
        raise ValueError("Order identity or market mismatch")
    volume = _amount(order.get("vol"), positive=True)
    filled, cost = _amount(order.get("vol_exec")), _amount(order.get("cost"))
    status = order.get("status")
    if (status not in TERMINAL | {"pending", "open"} or filled > volume
            or (status == "closed" and filled != volume)):
        raise ValueError("Invalid order status")
    if binding["side"] == "buy":
        limit = _amount(descr.get("price"), positive=True)
        if (descr.get("ordertype") != "limit" or volume > _amount(intent["order_volume"])
                or limit > _amount(intent["order_limit_price"]) or cost > limit * filled
                or limit * volume > _amount(str(intent["position_eurc"]))):
            raise ValueError("Buy exceeds approved terms")
    trade_ids = _ids(order.get("trades", []))
    if set(trades) != set(trade_ids):
        raise ValueError("Missing or unrelated fills")
    normalized, seen_ledgers = {}, set()
    base = base_symbol(intent["pair"])
    for trade_id in trade_ids:
        trade = trades[trade_id]
        if (not isinstance(trade, Mapping) or trade.get("ordertxid") != binding["order_id"]
                or trade.get("type") != binding["side"]
                or base_symbol(str(trade.get("pair", ""))) != base
                or _amount(trade.get("margin")) != 0):
            raise ValueError("Fill identity or market mismatch")
        qty, fill_cost = _amount(trade.get("vol"), positive=True), _amount(trade.get("cost"), positive=True)
        ledger_ids = _ids(trade.get("ledgers"))
        # Unsupported extra fee assets/credit systems remain unreconciled.
        if len(ledger_ids) != 2:
            raise ValueError("Expected base and EURC ledgers")
        movements = {}
        for ledger_id in ledger_ids:
            ledger = ledgers.get(ledger_id)
            if (ledger_id in seen_ledgers or not isinstance(ledger, Mapping)
                    or ledger.get("refid") != trade_id or ledger.get("type") != "trade"
                    or ledger.get("aclass") != "currency" or ledger.get("subtype", "") != ""):
                raise ValueError("Ledger identity mismatch")
            asset = ledger.get("asset")
            if not isinstance(asset, str) or not asset.isalnum() or asset != asset.upper():
                raise ValueError("Unsupported ledger asset")
            asset = "EURC" if asset == "EURC" else base_symbol(asset + "/EURC")
            if asset not in {base, "EURC"} or asset in movements:
                raise ValueError("Unexpected ledger asset")
            amount = _amount(ledger.get("amount"), signed=True)
            fee = _amount(ledger.get("fee"))
            movements[asset] = {"id": ledger_id, "amount": _text(amount), "fee": _text(fee)}
            seen_ledgers.add(ledger_id)
        direction = Decimal(1 if binding["side"] == "buy" else -1)
        if (set(movements) != {base, "EURC"}
                or _amount(movements[base]["amount"], signed=True) != direction * qty
                or _amount(movements["EURC"]["amount"], signed=True) != -direction * fill_cost):
            raise ValueError("Fill and ledger amounts disagree")
        base_fee, quote_fee = (_amount(movements[asset]["fee"]) for asset in (base, "EURC"))
        if base_fee >= qty or quote_fee >= fill_cost:
            raise ValueError("Unexpected fee amount")
        normalized[trade_id] = {"volume": _text(qty), "cost": _text(fill_cost),
                                "base_fee": _text(base_fee), "quote_fee": _text(quote_fee),
                                "ledgers": movements}
    if (seen_ledgers != set(ledgers)
            or sum((_amount(fill["volume"]) for fill in normalized.values()), Decimal(0)) != filled
            or sum((_amount(fill["cost"]) for fill in normalized.values()), Decimal(0)) != cost):
        raise ValueError("Incomplete fill totals")
    return {"status": status, "filled": _text(filled), "cost": _text(cost),
            "trade_ids": sorted(trade_ids)}, normalized


class PositionLedger:
    def __init__(self, database):
        self.entries = EntryJournal(database)
        with self.entries._connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS position_orders (
                    order_id TEXT PRIMARY KEY,
                    entry_client_id TEXT NOT NULL REFERENCES entry_attempts(client_order_id),
                    expected_client_id TEXT NOT NULL UNIQUE,
                    side TEXT NOT NULL CHECK(side IN ('buy','sell')),
                    report_json TEXT,
                    last_issue TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS position_fills (
                    trade_id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL REFERENCES position_orders(order_id),
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS position_ledger_links (
                    ledger_id TEXT PRIMARY KEY,
                    trade_id TEXT NOT NULL REFERENCES position_fills(trade_id)
                );
            """)

    @staticmethod
    def _bind(db, entry_id, order_id, client_id, side):
        if not isinstance(order_id, str) or not order_id or len(order_id) > 128:
            raise ValueError("Missing exchange order ID")
        existing = db.execute("SELECT * FROM position_orders WHERE order_id=? OR expected_client_id=?",
                              (order_id, client_id)).fetchall()
        if existing:
            if len(existing) != 1 or any(existing[0][key] != value for key, value in (
                    ("order_id", order_id), ("entry_client_id", entry_id),
                    ("expected_client_id", client_id), ("side", side))):
                raise ValueError("Order is already linked differently")
            return
        db.execute("""INSERT INTO position_orders
            (order_id,entry_client_id,expected_client_id,side,updated_at) VALUES(?,?,?,?,?)""",
            (order_id, entry_id, client_id, side, _now()))

    def track_exit(self, entry_client_id: str, exit_client_id: str, exchange_order_id: str):
        """Link an executor's already identified sell; this never authorizes one.

        The future executor must persist its exit intent before sending, resolve
        unknown attempts and reserve inventory independently. Accounting must not
        be used as a replacement for those submission/duplicate guards.
        """
        if str(uuid.UUID(exit_client_id)) != exit_client_id or exit_client_id == entry_client_id:
            raise ValueError("Expected a separate canonical exit UUID")
        with self.entries._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            entry = self.entries._row(db, entry_client_id)
            self._bind(db, entry_client_id, entry["exchange_order_id"], entry_client_id, "buy")
            self._bind(db, entry_client_id, exchange_order_id, exit_client_id, "sell")

    def reconcile(self, entry_client_id: str, client) -> dict:
        """Refresh only linked orders and preserve proven fills on read failures."""
        with self.entries._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            entry = self.entries._row(db, entry_client_id)
            self._bind(db, entry_client_id, entry["exchange_order_id"], entry_client_id, "buy")
            orders = [dict(row) for row in db.execute(
                "SELECT * FROM position_orders WHERE entry_client_id=? ORDER BY side,order_id", (entry_client_id,))]
            intent = json.loads(entry["intent_json"])
        for binding in orders:
            try:
                report = client.settlement_for_order(binding["order_id"])
            except Exception:
                self._issue(binding["order_id"], "lookup_incomplete")
                continue
            try:
                with localcontext() as context:
                    context.prec = 80
                    snapshot, fills = _normalize_settlement(binding, intent, report)
                    self._apply(binding["order_id"], snapshot, fills)
            except (ValueError, TypeError, KeyError, InvalidOperation):
                self._issue(binding["order_id"], "settlement_conflict")
        return self.get(entry_client_id)

    def _issue(self, order_id, issue):
        with self.entries._connection() as db:
            db.execute("UPDATE position_orders SET last_issue=?,updated_at=? WHERE order_id=?",
                       (issue, _now(), order_id))

    def _apply(self, order_id, snapshot, fills):
        with self.entries._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT report_json FROM position_orders WHERE order_id=?", (order_id,)).fetchone()[0]
            old = json.loads(old) if old else None
            # Validate repeated records even in stale snapshots; never overwrite a fill.
            for trade_id, fill in fills.items():
                existing = db.execute("SELECT * FROM position_fills WHERE trade_id=?", (trade_id,)).fetchone()
                if existing and (existing["order_id"] != order_id or existing["payload_json"] != _json(fill)):
                    raise ValueError("Conflicting immutable fill")
                for movement in fill["ledgers"].values():
                    linked = db.execute("SELECT trade_id FROM position_ledger_links WHERE ledger_id=?",
                                        (movement["id"],)).fetchone()
                    if linked and linked[0] != trade_id:
                        raise ValueError("Ledger already counted for another fill")
            if old:
                previous, incoming = set(old["trade_ids"]), set(snapshot["trade_ids"])
                if incoming < previous:
                    return  # Older complete snapshot, not a reason to subtract fills.
                if not previous <= incoming:
                    raise ValueError("Exchange replaced confirmed fills")
                if old["status"] in TERMINAL:
                    if incoming != previous:
                        raise ValueError("New fill after terminal reconciliation")
                    if snapshot["status"] not in TERMINAL:
                        return
                    if snapshot["status"] != old["status"]:
                        raise ValueError("Conflicting terminal state")
            for trade_id, fill in fills.items():
                db.execute("INSERT OR IGNORE INTO position_fills VALUES(?,?,?)", (trade_id, order_id, _json(fill)))
                for movement in fill["ledgers"].values():
                    db.execute("INSERT OR IGNORE INTO position_ledger_links VALUES(?,?)", (movement["id"], trade_id))
            db.execute("UPDATE position_orders SET report_json=?,last_issue=NULL,updated_at=? WHERE order_id=?",
                       (_json(snapshot), _now(), order_id))

    def get(self, entry_client_id: str) -> dict:
        with self.entries._connection() as db, localcontext() as context:
            context.prec = 80
            db.execute("BEGIN")  # One consistent snapshot across orders and fills.
            entry = self.entries._row(db, entry_client_id)
            intent = json.loads(entry["intent_json"])
            orders = db.execute("SELECT * FROM position_orders WHERE entry_client_id=?", (entry_client_id,)).fetchall()
            rows = db.execute("""SELECT f.*,o.side FROM position_fills f JOIN position_orders o USING(order_id)
                WHERE o.entry_client_id=?""", (entry_client_id,)).fetchall()
            bought = sold = spent = received = base_fees = quote_fees = Decimal(0)
            for row in rows:
                fill = json.loads(row["payload_json"])
                qty, cost = _amount(fill["volume"]), _amount(fill["cost"])
                base_fee, quote_fee = _amount(fill["base_fee"]), _amount(fill["quote_fee"])
                base_fees += base_fee
                quote_fees += quote_fee
                if row["side"] == "buy":
                    bought += qty
                    spent += cost + quote_fee
                else:
                    sold += qty
                    received += cost - quote_fee
            remaining = bought - sold - base_fees
            issues = {row["last_issue"] for row in orders if row["last_issue"]}
            if entry["last_issue"]:
                issues.add("entry_unresolved")
            if not orders or any(not row["report_json"] for row in orders):
                issues.add("settlement_pending")
            if remaining < 0:
                issues.add("inventory_shortfall")
            complete = not issues
            terminal = bool(orders) and all(row["report_json"] and json.loads(row["report_json"])["status"] in TERMINAL
                                           for row in orders)
            flat = complete and terminal and remaining == 0 and bought > 0
            return {"entry_client_id": entry_client_id, "pair": intent["pair"],
                    "bought_volume": _text(bought), "sold_volume": _text(sold),
                    "base_fees": _text(base_fees), "eurc_fees": _text(quote_fees),
                    "remaining_volume": _text(remaining), "eurc_spent": _text(spent),
                    "eurc_received": _text(received), "net_cash_flow_eurc": _text(received - spent),
                    "round_trip_pnl_eurc": _text(received - spent) if flat else None,
                    "accounting_complete": complete, "all_linked_orders_terminal": terminal,
                    "status": ("UNRECONCILED" if issues else "FLAT_RECONCILED" if flat else
                               "OPEN" if remaining else "NO_POSITION" if terminal else "ORDER_PENDING"),
                    "issues": sorted(issues), "fill_count": len(rows)}
