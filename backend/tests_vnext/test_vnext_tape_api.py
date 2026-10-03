from __future__ import annotations

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from app.vnext_tape import build_vnext_tape_snapshot
from aether_vnext.store import VNextStore
from aether_vnext.tape import (
    TapeCompositeObservation,
    TapeConsensusState,
    TapeSourceObservation,
    TapeSourceQuality,
)


UTC = timezone.utc
NOW = datetime(2026, 10, 3, 18, 20, tzinfo=UTC)


def _source(source: str, mark: float) -> TapeSourceObservation:
    received = NOW - timedelta(milliseconds=25)
    return TapeSourceObservation(
        observation_id=f"{source}-obs",
        asset_id="btc",
        source_id=source,
        venue=source,
        source_symbol="BTC-USD",
        contract_id=None,
        bid=mark - 0.5,
        ask=mark + 0.5,
        last=mark,
        mark=mark,
        exchange_ts=received,
        received_ts=received,
        age_ms=25,
        quality=TapeSourceQuality.HEALTHY,
        source_data_version="v1",
        source_ref=f"{source}:BTC-USD",
    )


def test_tape_api_snapshot_exposes_provenance_without_execution_authority(monkeypatch) -> None:
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    sources = (
        _source("a", 100000.0),
        _source("b", 100000.2),
        _source("c", 99999.9),
    )
    composite = TapeCompositeObservation(
        composite_id="cmp-1",
        asset_id="btc",
        observed_at_utc=NOW,
        state=TapeConsensusState.FULL,
        composite_mark=100000.03333333334,
        median_mark=100000.0,
        accepted_source_ids=("a", "b", "c"),
        rejected_source_ids=(),
        source_observation_ids=tuple(row.observation_id for row in sources),
        source_count=3,
        quorum_required=3,
        max_source_age_ms=25,
        agreement_bps=0.03,
        provenance_complete=True,
    )
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        for row in sources:
            store.record_tape_source_observation(conn, row, recorded_at_utc=NOW)
        store.record_tape_composite(conn, composite, recorded_at_utc=NOW)
        payload = build_vnext_tape_snapshot(conn, store=store, as_of_utc=NOW)

    assert payload["paper_only"] is True
    assert payload["live_blocked"] is True
    assert payload["authority"]["execution_permission"] is False
    assert payload["summary"]["asset_count"] == 1
    assert payload["summary"]["state_counts"] == {"FULL": 1}
    assert payload["assets"][0]["asset_id"] == "btc"
    assert payload["assets"][0]["source_count"] == 3
    assert len(payload["assets"][0]["sources"]) == 3
    databento = next(
        row for row in payload["source_registry"]
        if row["source_id"] == "databento_glbx_mbp1"
    )
    assert databento["state"] == "CREDENTIAL_REQUIRED"
