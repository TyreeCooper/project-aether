from __future__ import annotations

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from aether_vnext.evidence import EvidenceWindow, SampleDomain
from aether_vnext.store import VNextStore
from tests_vnext.held_out_support import record_provenanced_held_out


UTC = timezone.utc
T0 = datetime(2026, 9, 27, 0, 40, tzinfo=UTC)


def _window(window_id: str = "heldout-provenance-1") -> EvidenceWindow:
    return EvidenceWindow(
        evidence_window_id=window_id,
        route_id="eurusd:intraday:long",
        playbook_id="pb_fx_intraday_v1_2",
        playbook_version="1.2",
        policy_version="policy-provenance",
        configuration_hash="cfg-provenance",
        sample_domain=SampleDomain.HELD_OUT,
        first_timestamp_utc=T0 - timedelta(days=10),
        last_timestamp_utc=T0 - timedelta(days=9),
        n=2,
        immutable_trade_ids=("hist-1", "hist-2"),
        metrics_snapshot_hash="metrics-provenance-1",
        created_at_utc=T0 - timedelta(days=1),
    )


def _store() -> tuple[sa.Engine, VNextStore]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        conn.execute(
            store.tables["policy_snapshots"].insert().values(
                configuration_hash="cfg-provenance",
                policy_version="policy-provenance",
                effective_at_utc=T0 - timedelta(days=30),
                changed_by="test",
                change_reason="held-out provenance",
                payload={},
                created_at_utc=T0 - timedelta(days=30),
            )
        )
    return engine, store


def test_provenanced_held_out_window_binds_research_run_dataset_and_fold() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        provenance_hash = record_provenanced_held_out(
            conn,
            store,
            _window(),
        )
        row = conn.execute(
            sa.select(store.tables["held_out_evidence_provenance"])
        ).mappings().one()
        window = store.load_evidence_window(
            conn,
            evidence_window_id="heldout-provenance-1",
        )

    assert window is not None
    assert window.sample_domain is SampleDomain.HELD_OUT
    assert row["backtest_run_id"] == "run:heldout-provenance-1"
    assert row["dataset_snapshot_id"] == "dataset:heldout-provenance-1"
    assert row["fold_result_ids"] == ["fold:heldout-provenance-1"]
    assert row["provenance_hash"] == provenance_hash
    assert len(provenance_hash) == 64


def test_generic_held_out_row_is_not_research_provenance() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        store.record_evidence_window(conn, _window("unproven-heldout"))
        count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["held_out_evidence_provenance"]
            )
        ).scalar_one()
    assert count == 0
