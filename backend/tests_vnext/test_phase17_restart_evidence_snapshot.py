from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa

from aether_vnext.restart_evidence_snapshot import (
    collect_restart_evidence_snapshot,
)
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 21, 45, tzinfo=UTC)


def _engine_store():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        assert store.provision_seed_ledgers_once(conn) is True
    return engine, store


def test_restart_snapshot_is_deterministic_and_read_only() -> None:
    engine, store = _engine_store()
    with engine.connect() as conn:
        before_events = conn.execute(
            sa.select(sa.func.count()).select_from(store.tables["event_ledger"])
        ).scalar_one()
        first = collect_restart_evidence_snapshot(
            conn,
            store=store,
            snapshot_id="restart-before",
            deployed_revision="revision-1",
            scenario="mid_ticket",
            observed_at_utc=T0,
            source_artifact_ids=("artifact-before",),
        )
        second = collect_restart_evidence_snapshot(
            conn,
            store=store,
            snapshot_id="restart-before-repeat",
            deployed_revision="revision-1",
            scenario="mid_ticket",
            observed_at_utc=T0,
            source_artifact_ids=("artifact-before-repeat",),
        )
        after_events = conn.execute(
            sa.select(sa.func.count()).select_from(store.tables["event_ledger"])
        ).scalar_one()

    assert first.state_payload_hash == second.state_payload_hash
    assert first.state_payload == second.state_payload
    assert first.reconciliation_blockers == ()
    assert first.synthetic is False
    assert before_events == after_events == 0


def test_restart_snapshot_hash_changes_when_durable_cash_state_changes() -> None:
    engine, store = _engine_store()
    with engine.connect() as conn:
        before = collect_restart_evidence_snapshot(
            conn,
            store=store,
            snapshot_id="cash-before",
            deployed_revision="revision-1",
            scenario="open_trade",
            observed_at_utc=T0,
            source_artifact_ids=("artifact-cash-before",),
        )

    with engine.begin() as conn:
        conn.execute(
            store.tables["broker_account_ledgers"].update()
            .where(
                store.tables["broker_account_ledgers"].c.broker_account_id
                == "kraken_paper"
            )
            .values(cash_available_usd=3999.0, row_version=2)
        )

    with engine.connect() as conn:
        after = collect_restart_evidence_snapshot(
            conn,
            store=store,
            snapshot_id="cash-after",
            deployed_revision="revision-1",
            scenario="open_trade",
            observed_at_utc=T0,
            source_artifact_ids=("artifact-cash-after",),
        )

    assert before.state_payload_hash != after.state_payload_hash


def test_restart_snapshot_surfaces_runtime_reconciliation_blocker() -> None:
    engine, store = _engine_store()
    with engine.begin() as conn:
        conn.execute(
            store.tables["risk_admission_guard"].delete()
        )

    with engine.connect() as conn:
        snapshot = collect_restart_evidence_snapshot(
            conn,
            store=store,
            snapshot_id="restart-blocked",
            deployed_revision="revision-1",
            scenario="mid_order",
            observed_at_utc=T0,
            source_artifact_ids=("artifact-blocked",),
        )

    assert snapshot.reconciliation_blockers == (
        "risk_admission_reconciliation:firm_risk_guard_count:0",
    )
    assert snapshot.state_payload["risk_admission_issues"] == [
        "firm_risk_guard_count:0"
    ]
