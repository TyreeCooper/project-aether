from __future__ import annotations

from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from aether_vnext.store import VNextStore
from aether_vnext.tape import (
    TapeCompositeObservation,
    TapeConsensusState,
    TapeSourceObservation,
    TapeSourceQuality,
)


UTC = timezone.utc
NOW = datetime(2026, 10, 3, 17, 20, tzinfo=UTC)


def _source(observation_id: str, source_id: str, mark: float) -> TapeSourceObservation:
    return TapeSourceObservation(
        observation_id=observation_id,
        asset_id="mes",
        source_id=source_id,
        venue="CME",
        source_symbol="MESZ26",
        contract_id="MESZ26",
        bid=mark - 0.125,
        ask=mark + 0.125,
        last=mark,
        mark=mark,
        exchange_ts=NOW,
        received_ts=NOW,
        age_ms=20,
        quality=TapeSourceQuality.HEALTHY,
        source_data_version="v1",
        source_ref=f"{source_id}:MESZ26",
    )


def _store() -> tuple[sa.Engine, VNextStore]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
    return engine, store


def test_tape_source_observations_are_immutable_and_round_trip() -> None:
    engine, store = _store()
    source = _source("a1", "feed-a", 6800.25)
    with engine.begin() as conn:
        store.record_tape_source_observation(
            conn,
            source,
            recorded_at_utc=NOW,
        )
        loaded = store.load_tape_source_observation(
            conn,
            observation_id="a1",
        )
    assert loaded == source

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            store.record_tape_source_observation(
                conn,
                source,
                recorded_at_utc=NOW,
            )


def test_tape_composite_requires_persisted_source_lineage() -> None:
    engine, store = _store()
    composite = TapeCompositeObservation(
        composite_id="cmp-1",
        asset_id="mes",
        observed_at_utc=NOW,
        state=TapeConsensusState.FULL,
        composite_mark=6800.25,
        median_mark=6800.25,
        accepted_source_ids=("feed-a", "feed-b", "feed-c"),
        rejected_source_ids=(),
        source_observation_ids=("a1", "b1", "c1"),
        source_count=3,
        quorum_required=3,
        max_source_age_ms=20,
        agreement_bps=0.5,
        provenance_complete=True,
    )
    with engine.begin() as conn:
        with pytest.raises(ValueError, match="source lineage missing"):
            store.record_tape_composite(
                conn,
                composite,
                recorded_at_utc=NOW,
            )


def test_tape_composite_round_trip_preserves_full_provenance() -> None:
    engine, store = _store()
    sources = (
        _source("a1", "feed-a", 6800.25),
        _source("b1", "feed-b", 6800.25),
        _source("c1", "feed-c", 6800.50),
    )
    composite = TapeCompositeObservation(
        composite_id="cmp-1",
        asset_id="mes",
        observed_at_utc=NOW,
        state=TapeConsensusState.FULL,
        composite_mark=(6800.25 + 6800.25 + 6800.50) / 3,
        median_mark=6800.25,
        accepted_source_ids=("feed-a", "feed-b", "feed-c"),
        rejected_source_ids=(),
        source_observation_ids=("a1", "b1", "c1"),
        source_count=3,
        quorum_required=3,
        max_source_age_ms=20,
        agreement_bps=0.37,
        provenance_complete=True,
    )
    with engine.begin() as conn:
        for source in sources:
            store.record_tape_source_observation(
                conn,
                source,
                recorded_at_utc=NOW,
            )
        store.record_tape_composite(
            conn,
            composite,
            recorded_at_utc=NOW,
        )
        loaded = store.latest_tape_composite(conn, asset_id="mes")
    assert loaded == composite
