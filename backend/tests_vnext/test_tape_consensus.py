from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.tape import TapeSourceObservation, TapeSourceQuality
from aether_vnext.tape_consensus import qualify_tape_sources
from aether_vnext.tape_policy import TapeAssetClass, TapeQuorumPolicy


UTC = timezone.utc
NOW = datetime(2026, 10, 3, 17, 30, tzinfo=UTC)
POLICY = TapeQuorumPolicy(
    asset_class=TapeAssetClass.FUTURES,
    max_source_age_ms=1000,
    max_divergence_bps=5.0,
)


def _obs(source: str, *, age_ms: int = 25, quality=TapeSourceQuality.HEALTHY,
         contract_id: str | None = "MESZ26", mark: float | None = 6800.25,
         suffix: str = "1") -> TapeSourceObservation:
    return TapeSourceObservation(
        observation_id=f"{source}-{suffix}",
        asset_id="mes",
        source_id=source,
        venue="CME",
        source_symbol="MESZ26",
        contract_id=contract_id,
        bid=None if mark is None else mark - 0.125,
        ask=None if mark is None else mark + 0.125,
        last=mark,
        mark=mark,
        exchange_ts=NOW - timedelta(milliseconds=age_ms),
        received_ts=NOW - timedelta(milliseconds=age_ms),
        age_ms=age_ms,
        quality=quality,
        source_data_version="v1",
        source_ref=f"{source}:MESZ26",
    )


def test_qualification_accepts_fresh_identity_matched_independent_sources() -> None:
    result = qualify_tape_sources(
        (_obs("a"), _obs("b"), _obs("c")),
        asset_id="mes",
        policy=POLICY,
        as_of_utc=NOW,
        expected_contract_id="MESZ26",
    )
    assert tuple(row.source_id for row in result.accepted) == ("a", "b", "c")
    assert result.rejected == ()


def test_stale_invalid_and_contract_mismatch_remain_distinct_reasons() -> None:
    result = qualify_tape_sources(
        (
            _obs("stale", age_ms=1500),
            _obs("invalid", quality=TapeSourceQuality.INVALID),
            _obs("wrong", contract_id="MESH27"),
        ),
        asset_id="mes",
        policy=POLICY,
        as_of_utc=NOW,
        expected_contract_id="MESZ26",
    )
    assert result.accepted == ()
    assert {row.source_id: row.reason for row in result.rejected} == {
        "invalid": "source_invalid",
        "stale": "source_stale",
        "wrong": "contract_identity_mismatch",
    }


def test_latest_observation_per_source_wins_without_counting_source_twice() -> None:
    older = _obs("a", age_ms=100, suffix="old")
    newer = _obs("a", age_ms=10, suffix="new")
    result = qualify_tape_sources(
        (older, newer),
        asset_id="mes",
        policy=POLICY,
        as_of_utc=NOW,
        expected_contract_id="MESZ26",
    )
    assert tuple(row.observation_id for row in result.accepted) == ("a-new",)
    assert result.rejected[0].reason == "superseded_source_observation"


def test_unbound_policy_cannot_qualify_sources() -> None:
    with pytest.raises(RuntimeError, match="not operational"):
        qualify_tape_sources(
            (_obs("a"),),
            asset_id="mes",
            policy=TapeQuorumPolicy(asset_class=TapeAssetClass.FUTURES),
            as_of_utc=NOW,
            expected_contract_id="MESZ26",
        )
