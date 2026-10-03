from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.tape import (
    TapeConsensusState,
    TapeSourceObservation,
    TapeSourceQuality,
)
from aether_vnext.tape_consensus import (
    build_tape_composite,
    decide_tape_consensus,
    qualify_tape_sources,
)
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


def _decision(*rows: TapeSourceObservation):
    qualification = qualify_tape_sources(
        rows,
        asset_id="mes",
        policy=POLICY,
        as_of_utc=NOW,
        expected_contract_id="MESZ26",
    )
    return decide_tape_consensus(
        qualification,
        policy=POLICY,
        as_of_utc=NOW,
    )


def test_three_agreeing_sources_form_full_consensus() -> None:
    decision = _decision(
        _obs("a", mark=6800.00),
        _obs("b", mark=6800.25),
        _obs("c", mark=6800.50),
    )
    assert decision.state is TapeConsensusState.FULL
    assert len(decision.inliers) == 3
    assert decision.outliers == ()
    assert decision.median_mark == 6800.25


def test_one_bad_feed_cannot_drag_four_agreeing_sources() -> None:
    decision = _decision(
        _obs("a", mark=6800.00),
        _obs("b", mark=6800.25),
        _obs("c", mark=6800.50),
        _obs("d", mark=6800.25),
        _obs("bad", mark=6500.00),
    )
    assert decision.state is TapeConsensusState.FULL
    assert {row.source_id for row in decision.inliers} == {"a", "b", "c", "d"}
    assert tuple(row.source_id for row in decision.outliers) == ("bad",)


def test_three_fresh_sources_without_three_source_agreement_are_contested() -> None:
    decision = _decision(
        _obs("a", mark=6800.00),
        _obs("b", mark=6800.25),
        _obs("c", mark=7000.00),
    )
    assert decision.state is TapeConsensusState.CONTESTED
    assert len(decision.inliers) == 2
    assert tuple(row.source_id for row in decision.outliers) == ("c",)


def test_two_agreeing_sources_are_degraded_not_full() -> None:
    decision = _decision(
        _obs("a", mark=6800.00),
        _obs("b", mark=6800.25),
    )
    assert decision.state is TapeConsensusState.DEGRADED
    assert len(decision.inliers) == 2


def test_single_qualified_source_stays_single_source() -> None:
    decision = _decision(_obs("a", mark=6800.00))
    assert decision.state is TapeConsensusState.SINGLE_SOURCE
    assert len(decision.inliers) == 1


def test_composite_is_mean_of_inliers_only_after_outlier_rejection() -> None:
    decision = _decision(
        _obs("a", mark=6800.00),
        _obs("b", mark=6800.25),
        _obs("c", mark=6800.50),
        _obs("d", mark=6800.25),
        _obs("bad", mark=6500.00),
    )
    composite = build_tape_composite(
        decision,
        policy=POLICY,
        observed_at_utc=NOW,
    )
    assert composite.state is TapeConsensusState.FULL
    assert composite.composite_mark == pytest.approx(
        (6800.00 + 6800.25 + 6800.50 + 6800.25) / 4
    )
    assert "bad" in composite.rejected_source_ids
    assert composite.source_count == 4
    assert composite.quorum_required == 3
    assert composite.provenance_complete is True
    assert composite.confidence.value == "HIGH"
    assert composite.can_authorize_execution is False


def test_contested_sources_never_publish_averaged_mark() -> None:
    decision = _decision(
        _obs("a", mark=6800.00),
        _obs("b", mark=6800.25),
        _obs("c", mark=7000.00),
    )
    composite = build_tape_composite(
        decision,
        policy=POLICY,
        observed_at_utc=NOW,
    )
    assert composite.state is TapeConsensusState.CONTESTED
    assert composite.composite_mark is None
    assert composite.confidence.value == "CONTESTED"


def test_two_source_composite_is_visible_but_only_medium_confidence() -> None:
    decision = _decision(
        _obs("a", mark=6800.00),
        _obs("b", mark=6800.25),
    )
    composite = build_tape_composite(
        decision,
        policy=POLICY,
        observed_at_utc=NOW,
    )
    assert composite.state is TapeConsensusState.DEGRADED
    assert composite.composite_mark == pytest.approx(6800.125)
    assert composite.confidence.value == "MEDIUM"
