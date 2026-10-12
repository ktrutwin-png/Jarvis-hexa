from datetime import datetime, timedelta, timezone
import threading

from heksa import market_monitor as module


def proposal(identifier="first", price=100):
    return {
        "proposal_id": identifier, "pair": "XBT/EURC", "status": "PROPOSAL",
        "requires_user_approval": True,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "position_eurc": 10, "estimated_round_trip_cost_bps": 80,
        "signal": {"signal": "BUY_CANDIDATE", "last_price": price,
                   "stop_loss": price * 0.995, "take_profit": price * 1.02},
        "execution": {"executable": True, "average_price": price},
        "opportunity": {"taker_fee_bps": 40},
    }


def test_unchanged_terms_preserve_id_and_expiry(tmp_path, monkeypatch):
    monitor = module.MarketMonitor(tmp_path)
    monkeypatch.setattr(module, "build_best_eurc_proposals", lambda **_: {"proposals": [proposal()]})
    monitor.scan_once()
    first = monitor.snapshot()["proposal"]
    monkeypatch.setattr(module, "build_best_eurc_proposals", lambda **_: {"proposals": [proposal("second")]})
    monitor.scan_once()
    assert monitor.snapshot()["proposal"] == first
    monkeypatch.setattr(module, "utc_now", lambda: datetime.fromisoformat(first["expires_at"]) + timedelta(seconds=1))
    assert monitor.snapshot()["proposal"] is None
    assert not monitor.reject(first["proposal_id"])


def test_rejection_survives_failure_and_restart(tmp_path, monkeypatch):
    monitor = module.MarketMonitor(tmp_path)
    monkeypatch.setattr(module, "build_best_eurc_proposals", lambda **_: {"proposals": [proposal()]})
    monitor.scan_once()
    assert monitor.reject("first")
    assert not monitor.reject("first")
    def fail(**_):
        raise RuntimeError("offline")
    monkeypatch.setattr(module, "build_best_eurc_proposals", fail)
    assert not monitor.scan_once()
    restored = module.MarketMonitor(tmp_path)
    assert "XBT/EURC" in restored.journal.rejected_pairs()
    assert restored.snapshot()["proposal"] is None


def test_stop_discards_inflight_scan_and_prevents_overlap(tmp_path, monkeypatch):
    monitor = module.MarketMonitor(tmp_path)
    entered, release = threading.Event(), threading.Event()
    def scan(**_):
        entered.set()
        assert release.wait(2)
        return {"proposals": [proposal()]}
    monkeypatch.setattr(module, "build_best_eurc_proposals", scan)
    worker = threading.Thread(target=monitor.scan_once)
    worker.start()
    try:
        assert entered.wait(2)
        assert not monitor.scan_once()
        monitor.stop()
    finally:
        release.set()
        worker.join(2)
    assert not worker.is_alive()
    assert monitor.snapshot()["proposal"] is None


def test_old_notification_cannot_reject_new_price(tmp_path, monkeypatch):
    monitor = module.MarketMonitor(tmp_path)
    monkeypatch.setattr(module, "build_best_eurc_proposals", lambda **_: {"proposals": [proposal()]})
    monitor.scan_once()
    monkeypatch.setattr(module, "build_best_eurc_proposals", lambda **_: {"proposals": [proposal("new", 101)]})
    monitor.scan_once()
    assert not monitor.reject("first")
    assert monitor.snapshot()["proposal"]["proposal_id"] == "new"


def test_reject_during_refresh_cannot_resurrect_proposal(tmp_path, monkeypatch):
    monitor = module.MarketMonitor(tmp_path)
    monkeypatch.setattr(module, "build_best_eurc_proposals", lambda **_: {"proposals": [proposal()]})
    monitor.scan_once()
    entered, release = threading.Event(), threading.Event()
    def scan(**_):
        entered.set()
        assert release.wait(2)
        return {"proposals": [proposal("late")]}
    monkeypatch.setattr(module, "build_best_eurc_proposals", scan)
    worker = threading.Thread(target=monitor.scan_once)
    worker.start()
    try:
        assert entered.wait(2)
        assert monitor.reject("first")
    finally:
        release.set()
        worker.join(2)
    assert monitor.snapshot()["proposal"] is None
    assert "XBT/EURC" in monitor.journal.rejected_pairs()
