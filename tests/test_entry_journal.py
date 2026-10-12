from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import threading

import pytest

from heksa.entry_journal import EntryJournal
from heksa.kraken import KrakenClient
from heksa.trade_intent import build_trade_intent
from tests.test_trade_intent import proposal


def claim(journal, item, fingerprint=None, **changes):
    now = datetime.now(timezone.utc)
    values = dict(current_ask=100.1, quote_time=now, available_eurc=10.1,
                  estimated_entry_fee_eurc=0.04, estimated_round_trip_cost_eurc=0.085,
                  current_market_rules=item["opportunity"]["market_rules"])
    values.update(changes)
    return journal.claim(item, fingerprint or build_trade_intent(item).fingerprint, **values)


def observed(client_id, *, status="open", filled="0", cost="0"):
    return {"cl_ord_id": client_id, "status": status, "vol": "0.099",
            "vol_exec": filled, "cost": cost, "fee": "0",
            "descr": {"pair": "XBTEURC", "type": "buy", "ordertype": "limit",
                      "price": "100.1", "leverage": "none"}}


def reconcile(journal, client_id, order):
    return journal.reconcile(client_id, SimpleNamespace(
        orders_by_client_id=lambda _: {"EXCHANGE-1": order}))


def test_concurrent_duplicate_clicks_across_instances_claim_exactly_once(tmp_path):
    path = tmp_path / "entries.sqlite3"
    journals = [EntryJournal(path), EntryJournal(path)]
    item = proposal()
    barrier = threading.Barrier(2)
    def run(journal):
        barrier.wait(timeout=2)
        return claim(journal, item)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, journals))
    assert sum(result["new_attempt"] for result in results) == 1
    assert len({result["client_order_id"] for result in results}) == 1
    assert len(journals[0].active()) == 1


def test_restart_timeout_and_expiry_never_authorize_resubmission(tmp_path):
    path = tmp_path / "entries.sqlite3"
    journal = EntryJournal(path)
    item = proposal()
    first = claim(journal, item)
    journal.note_uncertain(first["client_order_id"])
    item["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    result = claim(EntryJournal(path), item, first["fingerprint"])
    assert not result["new_attempt"]
    assert result["client_order_id"] == first["client_order_id"]
    assert result["state"] == "UNKNOWN"
    with pytest.raises(PermissionError, match="differs"):
        claim(journal, item, "changed-approval")


def test_invalid_preflight_leaves_no_attempt(tmp_path):
    journal = EntryJournal(tmp_path / "entries.sqlite3")
    with pytest.raises(ValueError):
        claim(journal, proposal(), available_eurc=0)
    assert journal.active() == []


def test_empty_lookup_keeps_uncertainty_and_blocks_another_entry(tmp_path):
    journal = EntryJournal(tmp_path / "entries.sqlite3")
    first = claim(journal, proposal())
    result = journal.reconcile(first["client_order_id"], SimpleNamespace(orders_by_client_id=lambda _: {}))
    assert result["state"] == "UNKNOWN"
    item = proposal()
    item["proposal_id"] = "next"
    with pytest.raises(PermissionError, match="reconciled"):
        claim(journal, item)


def test_acknowledgement_is_not_a_fill(tmp_path):
    journal = EntryJournal(tmp_path / "entries.sqlite3")
    first = claim(journal, proposal())
    result = journal.record_response(first["client_order_id"], {"error": [], "result": {"txid": ["EXCHANGE-1"]}})
    assert result["state"] == "ACKNOWLEDGED"
    assert result["filled_volume"] == "0"


def test_partial_fill_cancellation_keeps_position_and_late_data_cannot_erase_it(tmp_path):
    journal = EntryJournal(tmp_path / "entries.sqlite3")
    first = claim(journal, proposal())
    client_id = first["client_order_id"]
    result = reconcile(journal, client_id, observed(client_id, status="canceled", filled="0.04", cost="4.004"))
    assert result["state"] == "ENTRY_COMPLETE"
    assert result["filled_volume"] == "0.04"
    result = reconcile(journal, client_id, observed(client_id))
    assert result["state"] == "ENTRY_COMPLETE"
    assert result["filled_volume"] == "0.04"
    result = journal.record_response(client_id, {"error": [], "result": {"txid": ["EXCHANGE-1"]}})
    assert result["state"] == "ENTRY_COMPLETE"
    item = proposal()
    item["proposal_id"] = "next"
    with pytest.raises(PermissionError):
        claim(journal, item)


@pytest.mark.parametrize("field,value", [("vol_exec", "NaN"), ("vol_exec", "1"), ("cl_ord_id", "wrong")])
def test_invalid_order_data_never_releases_entry_guard(tmp_path, field, value):
    journal = EntryJournal(tmp_path / "entries.sqlite3")
    first = claim(journal, proposal())
    order = observed(first["client_order_id"])
    order[field] = value
    result = reconcile(journal, first["client_order_id"], order)
    assert result["state"] == "UNKNOWN"
    assert result["last_issue"] == "invalid_order"


def test_proven_zero_fill_allows_new_proposal_but_not_resending_old_one(tmp_path):
    journal = EntryJournal(tmp_path / "entries.sqlite3")
    item = proposal()
    first = claim(journal, item)
    result = reconcile(journal, first["client_order_id"], observed(first["client_order_id"], status="canceled"))
    assert result["state"] == "NO_FILL"
    assert not claim(journal, item)["new_attempt"]
    item["proposal_id"] = "new-consent"
    assert claim(journal, item)["new_attempt"]


def test_conflicting_order_after_zero_fill_blocks_new_entry(tmp_path):
    journal = EntryJournal(tmp_path / "entries.sqlite3")
    first = claim(journal, proposal())
    client_id = first["client_order_id"]
    reconcile(journal, client_id, observed(client_id, status="canceled"))
    journal.record_response(client_id, {"error": [], "result": {"txid": ["DIFFERENT-ORDER"]}})
    item = proposal()
    item["proposal_id"] = "another"
    with pytest.raises(PermissionError):
        claim(journal, item)
    assert journal.active()[0]["last_issue"] == "conflicting_orders"


def test_kraken_lookup_reads_closed_orders_and_never_calls_add_order():
    client_id = "6d1b345e-2821-40e2-ad83-4ecb18a06876"
    calls = []
    def request(endpoint, params, timeout):
        calls.append((endpoint, params, timeout))
        if endpoint == "OpenOrders":
            return {"error": [], "result": {"open": {"EXCHANGE-1": observed(client_id)}}}
        return {"error": [], "result": {"count": 1, "closed": {
            "EXCHANGE-1": observed(client_id, status="closed", filled="0.099", cost="9.9099")}}}
    client = KrakenClient.__new__(KrakenClient)
    client.api = SimpleNamespace(query_private=request)
    result = client.orders_by_client_id(client_id)
    assert result["EXCHANGE-1"]["status"] == "closed"
    assert [call[0] for call in calls] == ["OpenOrders", "ClosedOrders"]
    assert all(call[1]["cl_ord_id"] == client_id and call[2] == 15 for call in calls)


def test_incomplete_history_is_an_error_not_an_empty_success():
    client = KrakenClient.__new__(KrakenClient)
    client.api = SimpleNamespace(query_private=lambda endpoint, *_, **__: {
        "error": [], "result": {"open": {}} if endpoint == "OpenOrders" else {"closed": {}, "count": 1}})
    with pytest.raises(RuntimeError, match="Incomplete"):
        client.orders_by_client_id("6d1b345e-2821-40e2-ad83-4ecb18a06876")
