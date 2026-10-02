from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.vnext_operator import create_vnext_operator_router


def _snapshot() -> dict[str, object]:
    return {
        "as_of_utc": "2026-10-01T04:20:00+00:00",
        "mode": {
            "paper_only": True,
            "live_blocked": True,
            "forced_entries_enabled": False,
            "natural_setups_only": True,
        },
        "authority": {
            "read_only_projection": True,
            "execution_permission": False,
            "may_mutate_firm_state": False,
            "legacy_fallback_allowed": False,
        },
        "paper_test": {
            "epoch_id": "aether-prototype-new-system-test-001",
            "started_at_utc": "2026-10-01T00:00:00+00:00",
            "seed_bank_usd": 10000.0,
        },
        "bank": {
            "cash_available_usd": 10000.0,
            "cash_reserved_usd": 0.0,
            "book_cash_usd": 10000.0,
            "realized_pnl_usd": 0.0,
            "unrealized_pnl_usd": 0.0,
            "fees_accrued_usd": 0.0,
            "carry_accrued_usd": 0.0,
            "ledger_count": 2,
        },
        "blotter": [],
        "activity": [],
        "ledgers": [],
    }


def test_operator_console_is_get_only_and_paper_safe() -> None:
    app = FastAPI()
    app.include_router(create_vnext_operator_router(_snapshot))
    client = TestClient(app)

    response = client.get("/api/v1/vnext/operator")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"]["paper_only"] is True
    assert body["mode"]["live_blocked"] is True
    assert body["mode"]["forced_entries_enabled"] is False
    assert body["authority"]["legacy_fallback_allowed"] is False
    assert body["paper_test"]["seed_bank_usd"] == 10000.0

    for method in ("post", "put", "patch", "delete"):
        assert getattr(client, method)("/api/v1/vnext/operator").status_code == 405


def test_operator_console_rejects_unsafe_snapshot() -> None:
    def unsafe() -> dict[str, object]:
        body = _snapshot()
        body["mode"] = {"paper_only": False, "live_blocked": True}
        return body

    app = FastAPI()
    app.include_router(create_vnext_operator_router(unsafe))
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/api/v1/vnext/operator")
    assert response.status_code == 500


def test_main_mounts_vnext_operator_without_legacy_fallback() -> None:
    backend = Path(__file__).resolve().parents[1]
    main = (backend / "app" / "main.py").read_text(encoding="utf-8")
    bridge = (backend / "app" / "vnext_operator.py").read_text(encoding="utf-8")

    assert "mount_configured_vnext_operator(app)" in main
    assert "open_vnext_engine" in bridge
    assert "closed_trades_current_paper_epoch" in bridge
    assert "legacy_fallback_allowed" in bridge
    assert "from app.desk" not in bridge
    assert "engine.start_loop" not in bridge


def test_operator_cold_start_does_not_fabricate_zero_book() -> None:
    class EmptyStore:
        tables = {"event_ledger": sa.table("event_ledger", sa.column("created_at_utc"), sa.column("event_id"))}
        def current_paper_test_epoch(self, conn): return None
        def closed_trades_current_paper_epoch(self, conn, limit=200): return ()
        def ledger_rows(self, conn): return ()

    class EmptyResult:
        def mappings(self): return self
        def __iter__(self): return iter(())

    class EmptyConn:
        def execute(self, stmt): return EmptyResult()

    snapshot = build_vnext_operator_snapshot(
        EmptyConn(),
        store=EmptyStore(),
        as_of_utc=datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc),
    )
    assert snapshot["binding_state"] == "BASELINE_PENDING"
    assert snapshot["paper_test"]["seed_bank_usd"] is None
    assert snapshot["bank"]["book_cash_usd"] is None
    assert snapshot["bank"]["cash_available_usd"] is None
    assert snapshot["bank"]["ledger_count"] is None
