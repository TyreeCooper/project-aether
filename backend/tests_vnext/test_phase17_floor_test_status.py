from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa

from aether_vnext.operator_floor import build_unified_firm_floor
from aether_vnext.shadow_floor_snapshot import build_shadow_floor_snapshot
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 22, 50, tzinfo=UTC)


def _engine_store():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        assert store.provision_seed_ledgers_once(conn) is True
    return engine, store


def test_floor_reports_canonical_seed_before_first_test_epoch() -> None:
    engine, store = _engine_store()
    with engine.connect() as conn:
        snapshot = build_shadow_floor_snapshot(
            conn,
            store=store,
            as_of_utc=T0,
        )
    payload = build_unified_firm_floor(snapshot)

    assert payload["paper_test"] == {
        "epoch_id": None,
        "started_at_utc": None,
        "seed_bank_usd": 10000.0,
        "blotter_trade_count": 0,
    }


def test_floor_reports_new_test_epoch_after_reset() -> None:
    engine, store = _engine_store()
    with engine.begin() as conn:
        store.start_new_paper_test_epoch(
            conn,
            epoch_id="new-system-001",
            started_at_utc=T0,
            reason="whole new system / whole new tests",
        )
        snapshot = build_shadow_floor_snapshot(
            conn,
            store=store,
            as_of_utc=T0,
        )

    payload = build_unified_firm_floor(snapshot)
    test_state = payload["paper_test"]
    assert test_state["epoch_id"] == "new-system-001"
    assert test_state["started_at_utc"] == T0.isoformat()
    assert test_state["seed_bank_usd"] == 10000.0
    assert test_state["blotter_trade_count"] == 0
