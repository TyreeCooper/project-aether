from __future__ import annotations

from datetime import datetime, timezone

import pytest
import sqlalchemy as sa

from aether_vnext.intelligence_audit import (
    IntelligenceShadowAudit,
    summarize_shadow_audits,
)
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 9, 0, tzinfo=UTC)


def _store() -> tuple[sa.Engine, VNextStore]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
    return engine, store


def _audit(
    *,
    audit_id: str = "audit-1",
    shadow_outcome: str = "WATCH",
) -> IntelligenceShadowAudit:
    return IntelligenceShadowAudit(
        audit_id=audit_id,
        opportunity_id="opp-1",
        route_id="btc:intraday:pb-test",
        as_of_utc=T0,
        baseline_configuration_hash="baseline-hash",
        shadow_configuration_hash="shadow-macro-hash",
        enabled_components=("macro",),
        baseline_outcome="WATCH",
        shadow_outcome=shadow_outcome,
        evidence_ids=("event-1", "health-1"),
        research_only=True,
        order_created=False,
        trade_influence_enabled=False,
    )


def test_shadow_audit_round_trip_is_idempotent_and_append_only() -> None:
    engine, store = _store()
    audit = _audit()

    with engine.begin() as conn:
        store.record_intelligence_shadow_audit(conn, audit)
        store.record_intelligence_shadow_audit(conn, audit)

    with engine.begin() as conn:
        loaded = store.load_intelligence_shadow_audit(
            conn,
            audit_id="audit-1",
        )
        rows = store.list_intelligence_shadow_audits(
            conn,
            opportunity_id="opp-1",
        )
        count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["intelligence_shadow_audits"]
            )
        ).scalar_one()

    assert loaded == audit
    assert rows == (audit,)
    assert count == 1
    assert loaded is not None
    assert loaded.research_only is True
    assert loaded.order_created is False
    assert loaded.trade_influence_enabled is False


def test_shadow_audit_rejects_conflicting_replay() -> None:
    engine, store = _store()
    with engine.begin() as conn:
        store.record_intelligence_shadow_audit(conn, _audit())

    with pytest.raises(
        ValueError,
        match="conflicting immutable intelligence shadow audit",
    ):
        with engine.begin() as conn:
            store.record_intelligence_shadow_audit(
                conn,
                _audit(shadow_outcome="HIDE"),
            )


def test_persisted_shadow_audits_support_component_cohort_summary() -> None:
    engine, store = _store()
    changed = _audit(audit_id="audit-changed", shadow_outcome="HIDE")
    unchanged = _audit(audit_id="audit-unchanged", shadow_outcome="WATCH")

    with engine.begin() as conn:
        store.record_intelligence_shadow_audit(conn, changed)
        store.record_intelligence_shadow_audit(conn, unchanged)

    with engine.begin() as conn:
        rows = store.list_intelligence_shadow_audits(conn)

    summary = summarize_shadow_audits(
        rows,
        enabled_components=("macro",),
    )
    assert summary["observations"] == 2
    assert summary["outcome_changed_count"] == 1
    assert summary["outcome_unchanged_count"] == 1
    assert summary["alpha_claim"] is None
    assert summary["trade_influence_enabled"] is False
