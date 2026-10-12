from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from types import SimpleNamespace
import uuid

import pytest

from heksa.kraken import KrakenClient
from heksa.position_ledger import PositionLedger
from tests.test_entry_journal import claim
from tests.test_trade_intent import proposal


def setup_position(tmp_path):
    path = tmp_path / "position.sqlite3"
    ledger = PositionLedger(path)
    entry = claim(ledger.entries, proposal())
    ledger.entries.record_response(entry["client_order_id"], {"error": [], "result": {"txid": ["BUY-1"]}})
    return ledger, entry["client_order_id"], path


def settlement(client_id, *, order_id="BUY-1", side="buy", status="canceled", fills=None):
    # Each tuple describes an actual execution, not an estimated order fee.
    if fills is None:
        fills = [("T-1", "0.05", "5", "0", "0.02")]
    trades, ledgers = {}, {}
    filled = cost = Decimal(0)
    for trade_id, qty, value, base_fee, quote_fee in fills:
        qty, value = Decimal(qty), Decimal(value)
        filled += qty
        cost += value
        sign = Decimal(1 if side == "buy" else -1)
        ids = [trade_id + "-B", trade_id + "-Q"]
        trades[trade_id] = {"ordertxid": order_id, "pair": "XBTEURC", "type": side,
                            "vol": str(qty), "cost": str(value), "margin": "0", "fee": "0.99", "ledgers": ids}
        for identity, asset, amount, fee in ((ids[0], "XXBT", sign * qty, base_fee),
                                             (ids[1], "EURC", -sign * value, quote_fee)):
            ledgers[identity] = {"refid": trade_id, "type": "trade", "subtype": "", "aclass": "currency",
                                 "asset": asset, "amount": str(amount), "fee": fee, "balance": "999999"}
    order = {"cl_ord_id": client_id, "status": status,
             "vol": str(filled) if status == "closed" else "0.0999",
             "vol_exec": str(filled), "cost": str(cost), "fee": "0.99", "trades": list(trades),
             "descr": {"pair": "XBTEURC", "type": side, "ordertype": "limit", "price": "100.1", "leverage": "none"}}
    return {"order": order, "trades": trades, "ledgers": ledgers}


def refresh(ledger, entry_id, reports):
    return ledger.reconcile(entry_id, SimpleNamespace(settlement_for_order=lambda order: reports[order]))


def test_partial_purchase_survives_cancel_restart_and_duplicate_lookups(tmp_path):
    ledger, entry_id, path = setup_position(tmp_path)
    reports = {"BUY-1": settlement(entry_id)}
    first = refresh(ledger, entry_id, reports)
    second = refresh(PositionLedger(path), entry_id, reports)
    assert first == second
    assert first["remaining_volume"] == "0.05"
    assert first["eurc_spent"] == "5.02"
    assert first["eurc_fees"] == "0.02"  # Not the order/trade fee estimate of 0.99.
    assert first["round_trip_pnl_eurc"] is None
    assert first["status"] == "OPEN" and first["fill_count"] == 1
    assert ledger.entries.active()  # Accounting never releases submission locks.


def test_fees_in_base_reduce_inventory_and_are_not_deducted_twice(tmp_path):
    ledger, entry_id, path = setup_position(tmp_path)
    reports = {"BUY-1": settlement(entry_id, fills=[("B", "0.05", "5", "0.0002", "0")])}
    bought = refresh(ledger, entry_id, reports)
    assert bought["remaining_volume"] == "0.0498"
    assert bought["eurc_spent"] == "5"
    exit_id = str(uuid.uuid4())
    ledger.track_exit(entry_id, exit_id, "SELL-1")
    reports["SELL-1"] = settlement(exit_id, order_id="SELL-1", side="sell", status="closed",
                                   fills=[("S", "0.0498", "5.0796", "0", "0.0203184")])
    closed = refresh(ledger, entry_id, reports)
    assert closed["status"] == "FLAT_RECONCILED"
    assert closed["remaining_volume"] == "0"
    assert closed["round_trip_pnl_eurc"] == "0.0592816"
    assert closed["base_fees"] == "0.0002"
    assert refresh(PositionLedger(path), entry_id, reports) == closed


def test_partial_exit_keeps_inventory_and_no_final_profit(tmp_path):
    ledger, entry_id, _ = setup_position(tmp_path)
    exit_id = str(uuid.uuid4())
    ledger.track_exit(entry_id, exit_id, "SELL-1")
    reports = {"BUY-1": settlement(entry_id), "SELL-1": settlement(
        exit_id, order_id="SELL-1", side="sell", fills=[("S", "0.02", "2.04", "0", "0.00816")])}
    result = refresh(ledger, entry_id, reports)
    assert result["remaining_volume"] == "0.03"
    assert result["eurc_received"] == "2.03184"
    assert result["round_trip_pnl_eurc"] is None
    assert result["status"] == "OPEN"


def test_sell_base_fee_and_loss_are_accounted_exactly(tmp_path):
    ledger, entry_id, _ = setup_position(tmp_path)
    exit_id = str(uuid.uuid4())
    ledger.track_exit(entry_id, exit_id, "SELL-1")
    reports = {"BUY-1": settlement(entry_id), "SELL-1": settlement(
        exit_id, order_id="SELL-1", side="sell", status="closed",
        fills=[("S", "0.0499", "4.95", "0.0001", "0")])}
    result = refresh(ledger, entry_id, reports)
    assert result["remaining_volume"] == "0"
    assert result["round_trip_pnl_eurc"] == "-0.07"


@pytest.mark.parametrize("fault", ["missing_ledger", "wrong_asset", "wrong_ref", "wrong_order", "margin",
                                    "wrong_pair", "missing_fill", "wrong_total", "nan", "float"])
def test_incomplete_or_unrelated_settlement_never_creates_inventory(tmp_path, fault):
    ledger, entry_id, _ = setup_position(tmp_path)
    report = settlement(entry_id)
    if fault == "missing_ledger": report["ledgers"].pop("T-1-Q")
    if fault == "wrong_asset": report["ledgers"]["T-1-Q"]["asset"] = "EUR"
    if fault == "wrong_ref": report["ledgers"]["T-1-Q"]["refid"] = "OTHER"
    if fault == "wrong_order": report["trades"]["T-1"]["ordertxid"] = "FOREIGN"
    if fault == "margin": report["trades"]["T-1"]["margin"] = "1"
    if fault == "wrong_pair": report["order"]["descr"]["pair"] = "XBT/EUR"
    if fault == "missing_fill": report["trades"] = {}
    if fault == "wrong_total": report["order"]["vol_exec"] = "0.06"
    if fault == "nan": report["ledgers"]["T-1-B"]["fee"] = "NaN"
    if fault == "float": report["trades"]["T-1"]["vol"] = 0.05
    result = refresh(ledger, entry_id, {"BUY-1": report})
    assert result["status"] == "UNRECONCILED"
    assert result["fill_count"] == 0 and result["remaining_volume"] == "0"
    assert result["round_trip_pnl_eurc"] is None


def test_timeout_preserves_proven_inventory_and_requires_fresh_reconciliation(tmp_path):
    ledger, entry_id, _ = setup_position(tmp_path)
    reports = {"BUY-1": settlement(entry_id)}
    refresh(ledger, entry_id, reports)
    uncertain = refresh(ledger, entry_id, {})  # Read error, not an empty position.
    assert uncertain["remaining_volume"] == "0.05" and not uncertain["accounting_complete"]
    assert refresh(ledger, entry_id, reports)["accounting_complete"]


def test_late_snapshot_cannot_remove_fills_or_reopen_terminal_order(tmp_path):
    ledger, entry_id, _ = setup_position(tmp_path)
    report = settlement(entry_id, status="open")
    refresh(ledger, entry_id, {"BUY-1": report})
    final = settlement(entry_id, fills=[("T-1", "0.05", "5", "0", "0.02"),
                                       ("T-2", "0.04", "4", "0", "0.016")])
    latest = refresh(ledger, entry_id, {"BUY-1": final})
    assert latest["remaining_volume"] == "0.09"
    assert refresh(ledger, entry_id, {"BUY-1": report}) == latest


def test_conflicting_fill_is_not_overwritten_and_retry_is_idempotent(tmp_path):
    ledger, entry_id, _ = setup_position(tmp_path)
    report = settlement(entry_id)
    refresh(ledger, entry_id, {"BUY-1": report})
    conflicting = deepcopy(report)
    conflicting["ledgers"]["T-1-Q"]["fee"] = "0.01"
    bad = refresh(ledger, entry_id, {"BUY-1": conflicting})
    assert bad["status"] == "UNRECONCILED" and bad["eurc_spent"] == "5.02"
    assert refresh(ledger, entry_id, {"BUY-1": report})["fill_count"] == 1


def test_inventory_shortfall_is_not_hidden_using_wallet_balance(tmp_path):
    ledger, entry_id, _ = setup_position(tmp_path)
    exit_id = str(uuid.uuid4())
    ledger.track_exit(entry_id, exit_id, "SELL-1")
    result = refresh(ledger, entry_id, {"BUY-1": settlement(entry_id), "SELL-1": settlement(
        exit_id, order_id="SELL-1", side="sell", status="closed", fills=[("S", "0.06", "6", "0", "0.02")])})
    assert result["remaining_volume"] == "-0.01"
    assert result["issues"] == ["inventory_shortfall"]
    assert result["round_trip_pnl_eurc"] is None


def test_open_buy_with_no_fills_is_pending_not_a_closed_position(tmp_path):
    ledger, entry_id, _ = setup_position(tmp_path)
    result = refresh(ledger, entry_id, {"BUY-1": settlement(entry_id, status="open", fills=[])})
    assert result["status"] == "ORDER_PENDING" and result["round_trip_pnl_eurc"] is None


def test_only_read_endpoints_and_exact_ledger_links_are_used(tmp_path):
    _, entry_id, _ = setup_position(tmp_path)
    report = settlement(entry_id)
    calls = []
    def query(endpoint, params, timeout):
        calls.append((endpoint, params, timeout))
        return {"error": [], "result": {"QueryOrders": {"BUY-1": report["order"]},
                                         "QueryTrades": report["trades"], "QueryLedgers": report["ledgers"]}[endpoint]}
    client = KrakenClient.__new__(KrakenClient)
    client.api = SimpleNamespace(query_private=query)
    assert client.settlement_for_order("BUY-1") == report
    assert [call[0] for call in calls] == ["QueryOrders", "QueryTrades", "QueryLedgers"]
    assert calls[1][1]["ledgers"] is True
    assert all(call[2] == 15 for call in calls)


def test_read_batch_limit_and_incomplete_lookup():
    client = KrakenClient.__new__(KrakenClient)
    calls = []
    def query(endpoint, params, timeout):
        ids = params["id"].split(",")
        calls.append(ids)
        return {"error": [], "result": {identity: {} for identity in ids}}
    client.api = SimpleNamespace(query_private=query)
    assert len(client._query_records("QueryLedgers", "id", [f"L-{i}" for i in range(43)])) == 43
    assert list(map(len, calls)) == [20, 20, 3]
    client.api.query_private = lambda *args, **kwargs: {"error": [], "result": {}}
    with pytest.raises(RuntimeError, match="Incomplete"):
        client.settlement_for_order("BUY-1")


def test_concurrent_reconciliation_counts_each_fill_once(tmp_path):
    ledger, entry_id, path = setup_position(tmp_path)
    ledgers = [ledger, PositionLedger(path)]
    reports = {"BUY-1": settlement(entry_id)}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda instance: refresh(instance, entry_id, reports), ledgers))
    assert all(result["fill_count"] == 1 and result["eurc_spent"] == "5.02" for result in results)


def test_same_ledger_id_cannot_be_counted_for_a_second_fill(tmp_path):
    ledger, entry_id, _ = setup_position(tmp_path)
    reports = {"BUY-1": settlement(entry_id)}
    refresh(ledger, entry_id, reports)
    exit_id = str(uuid.uuid4())
    ledger.track_exit(entry_id, exit_id, "SELL-1")
    sell = settlement(exit_id, order_id="SELL-1", side="sell", status="closed",
                      fills=[("S", "0.05", "5.10", "0", "0.02")])
    sell["trades"]["S"]["ledgers"][0] = "T-1-B"
    sell["ledgers"]["T-1-B"] = sell["ledgers"].pop("S-B")
    reports["SELL-1"] = sell
    result = refresh(ledger, entry_id, reports)
    assert result["status"] == "UNRECONCILED"
    assert result["fill_count"] == 1 and result["round_trip_pnl_eurc"] is None
