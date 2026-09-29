from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from aether_vnext.event_reactions import (
    EVENT_REACTION_HORIZONS,
    EventReactionMeasurement,
    materialize_event_reaction_rollup,
)
from aether_vnext.intelligence_health import (
    SourceClaim,
    SourceHealthInput,
    assess_cross_source_conflict,
    derive_source_health,
)
from aether_vnext.source_registry import (
    AssetSourceRecord,
    SourceTrustDecision,
)
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 5, 30, tzinfo=UTC)


def _store() -> tuple[sa.Engine, VNextStore]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
    return engine, store


def _source() -> AssetSourceRecord:
    return AssetSourceRecord(
        source_id="btc:reddit:bitcoin",
        asset_id="btc",
        source_type="community",
        platform="reddit",
        name="r/Bitcoin",
        url="https://www.reddit.com/r/Bitcoin/",
        tier="B",
        trust_state="candidate",
        origin="curated_seed",
        ingestion_mode="shadow",
        trade_influence_enabled=False,
    )


def _measurement(label: str, *, value: float = 0.01) -> EventReactionMeasurement:
    seconds = dict(EVENT_REACTION_HORIZONS)[label]
    return EventReactionMeasurement(
        event_id="event-1",
        asset_id="btc",
        event_at_utc=T0,
        information_available_at_utc=T0,
        horizon_seconds=seconds,
        observed_at_utc=T0 + timedelta(seconds=seconds),
        return_value=value,
        observation_id=f"obs-{label}",
        market_data_version="market-v1",
        research_only=True,
    )


def test_source_trust_decision_is_durable_and_audited() -> None:
    engine, store = _store()
    source = _source()

    with engine.begin() as conn:
        assert store.upsert_intelligence_source(conn, source) == 1
        trusted = store.record_source_trust_decision(
            conn,
            decision_id="decision-1",
            decision=SourceTrustDecision(
                source_id=source.source_id,
                prior_state="candidate",
                new_state="trusted",
                operator_id="operator-1",
                decided_at_utc=T0,
                rationale="approved for evidence handling",
            ),
        )

    assert trusted.trust_state == "trusted"
    assert trusted.trade_influence_enabled is False

    with engine.begin() as conn:
        loaded = store.load_intelligence_source(
            conn,
            source_id=source.source_id,
        )
        decision = conn.execute(
            sa.select(store.tables["source_trust_decisions"])
        ).mappings().one()
        row = conn.execute(
            sa.select(store.tables["intelligence_sources"])
        ).mappings().one()

    assert loaded is not None
    assert loaded.trust_state == "trusted"
    assert loaded.operator_approved_by == "operator-1"
    assert row["row_version"] == 2
    assert decision["prior_state"] == "candidate"
    assert decision["new_state"] == "trusted"


def test_source_metadata_cannot_bypass_trust_audit() -> None:
    engine, store = _store()
    source = _source()
    with engine.begin() as conn:
        store.upsert_intelligence_source(conn, source)

    with pytest.raises(ValueError, match="trust_state changes require"):
        with engine.begin() as conn:
            store.upsert_intelligence_source(
                conn,
                AssetSourceRecord(
                    **{
                        **{
                            name: getattr(source, name)
                            for name in source.__dataclass_fields__
                        },
                        "trust_state": "untrusted",
                    }
                ),
            )


def test_health_and_conflict_snapshots_round_trip_latest_state() -> None:
    engine, store = _store()
    health = derive_source_health(
        SourceHealthInput(
            source_id="macro:fed",
            configured=True,
            observed_at_utc=T0,
            last_success_at_utc=T0 - timedelta(seconds=30),
            stale_after_seconds=60,
        )
    )
    conflict = assess_cross_source_conflict(
        "macro:fomc:2026-09",
        (
            SourceClaim(
                source_id="fed",
                claim_key="macro:fomc:2026-09",
                value_fingerprint="hash-a",
                observed_at_utc=T0,
            ),
            SourceClaim(
                source_id="aggregator",
                claim_key="macro:fomc:2026-09",
                value_fingerprint="hash-b",
                observed_at_utc=T0,
            ),
        ),
        assessed_at_utc=T0,
    )

    with engine.begin() as conn:
        store.record_intelligence_health_snapshot(
            conn,
            health_snapshot_id="health-1",
            snapshot=health,
        )
        store.record_cross_source_conflict_assessment(
            conn,
            assessment_id="conflict-1",
            assessment=conflict,
        )

    with engine.begin() as conn:
        loaded_health = store.latest_intelligence_health_snapshot(
            conn,
            source_id="macro:fed",
        )
        loaded_conflict = store.latest_cross_source_conflict_assessment(
            conn,
            claim_key="macro:fomc:2026-09",
        )

    assert loaded_health is not None
    assert loaded_health.state == "healthy"
    assert loaded_health.trade_influence_enabled is False
    assert loaded_conflict is not None
    assert loaded_conflict.state == "conflict"
    assert loaded_conflict.source_ids == ("aggregator", "fed")
    assert loaded_conflict.trade_influence_enabled is False


def test_event_reaction_history_supports_partial_then_complete_rollups() -> None:
    engine, store = _store()
    partial_rows = (_measurement("5m"), _measurement("1h"))
    partial = materialize_event_reaction_rollup(
        partial_rows,
        materialized_at_utc=T0 + timedelta(hours=1),
    )
    complete_rows = tuple(
        _measurement(label)
        for label, _ in EVENT_REACTION_HORIZONS
    )
    complete = materialize_event_reaction_rollup(
        complete_rows,
        materialized_at_utc=T0 + timedelta(hours=24),
    )

    with engine.begin() as conn:
        store.record_event_reaction_rollup(
            conn,
            rollup_id="rollup-partial",
            rollup=partial,
        )
        store.record_event_reaction_rollup(
            conn,
            rollup_id="rollup-complete",
            rollup=complete,
        )

    with engine.begin() as conn:
        loaded_partial = store.load_event_reaction_rollup(
            conn,
            rollup_id="rollup-partial",
        )
        loaded_complete = store.load_event_reaction_rollup(
            conn,
            rollup_id="rollup-complete",
        )
        measurement_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["event_reaction_measurements"]
            )
        ).scalar_one()

    assert loaded_partial is not None
    assert loaded_partial.complete is False
    assert loaded_complete is not None
    assert loaded_complete.complete is True
    assert measurement_count == 6
    assert loaded_complete.research_only is True


def test_event_reaction_history_rejects_conflicting_canonical_horizon() -> None:
    engine, store = _store()
    original = materialize_event_reaction_rollup(
        (_measurement("5m"),),
        materialized_at_utc=T0 + timedelta(minutes=5),
    )
    conflicting_measurement = EventReactionMeasurement(
        event_id="event-1",
        asset_id="btc",
        event_at_utc=T0,
        information_available_at_utc=T0,
        horizon_seconds=5 * 60,
        observed_at_utc=T0 + timedelta(minutes=5),
        return_value=0.02,
        observation_id="obs-5m-revised",
        market_data_version="market-v1",
        research_only=True,
    )
    conflicting = materialize_event_reaction_rollup(
        (conflicting_measurement,),
        materialized_at_utc=T0 + timedelta(minutes=6),
    )

    with engine.begin() as conn:
        store.record_event_reaction_rollup(
            conn,
            rollup_id="rollup-original",
            rollup=original,
        )

    with pytest.raises(
        ValueError,
        match="conflicting event-reaction measurement",
    ):
        with engine.begin() as conn:
            store.record_event_reaction_rollup(
                conn,
                rollup_id="rollup-conflict",
                rollup=conflicting,
            )
