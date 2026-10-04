from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aether_vnext.tape import (
    MAX_TAPE_SOURCES,
    TapeCompositeObservation,
    TapeConsensusState,
    TapeSourceObservation,
    TapeSourceQuality,
)


UTC = timezone.utc
NOW = datetime(2026, 10, 3, 17, 0, tzinfo=UTC)


def _source(**overrides):
    payload = {
        "observation_id": "obs-1",
        "asset_id": "mes",
        "source_id": "feed-a",
        "venue": "CME",
        "source_symbol": "MESZ26",
        "contract_id": "MESZ26",
        "bid": 6800.0,
        "ask": 6800.25,
        "last": 6800.0,
        "mark": 6800.125,
        "exchange_ts": NOW,
        "received_ts": NOW,
        "age_ms": 25,
        "quality": TapeSourceQuality.HEALTHY,
        "source_data_version": "v1",
        "source_ref": "feed-a:MESZ26",
    }
    payload.update(overrides)
    return TapeSourceObservation(**payload)


def test_tape_source_observation_is_market_truth_not_execution_authority() -> None:
    row = _source()
    assert row.asset_id == "mes"
    assert row.can_authorize_execution is False


def test_tape_source_requires_canonical_identity_and_valid_book() -> None:
    with pytest.raises(ValueError, match="canonical lowercase"):
        _source(asset_id="MES")
    with pytest.raises(ValueError, match="bid cannot exceed ask"):
        _source(bid=6801.0, ask=6800.0)


def test_tape_composite_preserves_constituent_lineage() -> None:
    composite = TapeCompositeObservation(
        composite_id="cmp-1",
        asset_id="mes",
        observed_at_utc=NOW,
        state=TapeConsensusState.FULL,
        composite_mark=6800.25,
        median_mark=6800.25,
        accepted_source_ids=("feed-a", "feed-b", "feed-c"),
        rejected_source_ids=("feed-d",),
        source_observation_ids=("a1", "b1", "c1", "d1"),
        source_count=3,
        quorum_required=3,
        max_source_age_ms=91,
        agreement_bps=0.37,
        provenance_complete=True,
    )
    assert composite.source_count == 3
    assert composite.can_authorize_execution is False
    assert MAX_TAPE_SOURCES == 5


def test_not_observed_and_contested_cannot_publish_composite_mark() -> None:
    with pytest.raises(ValueError, match="NOT_OBSERVED"):
        TapeCompositeObservation(
            composite_id="cmp-none",
            asset_id="mes",
            observed_at_utc=NOW,
            state=TapeConsensusState.NOT_OBSERVED,
            composite_mark=1.0,
            median_mark=None,
            accepted_source_ids=(),
            rejected_source_ids=(),
            source_observation_ids=(),
            source_count=0,
            quorum_required=3,
            max_source_age_ms=None,
            agreement_bps=None,
            provenance_complete=False,
        )
    with pytest.raises(ValueError, match="CONTESTED"):
        TapeCompositeObservation(
            composite_id="cmp-contested",
            asset_id="mes",
            observed_at_utc=NOW,
            state=TapeConsensusState.CONTESTED,
            composite_mark=6800.0,
            median_mark=6800.0,
            accepted_source_ids=("a", "b", "c"),
            rejected_source_ids=(),
            source_observation_ids=("a1", "b1", "c1"),
            source_count=3,
            quorum_required=3,
            max_source_age_ms=50,
            agreement_bps=200.0,
            provenance_complete=True,
        )
