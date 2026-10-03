from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.allocator import (
    AllocationCandidate,
    allocate_fire_batch,
    allocator_version,
)
from aether_vnext.freeze import (
    ALLOCATOR_WEIGHTS,
    EvidenceState,
    GovernorState,
    OperationalState,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 26, 21, 0, tzinfo=UTC)


def _candidate(
    *,
    ticket_id: str,
    route_id: str,
    expectancy: float | None = 1.0,
    n: int = 30,
    ros: float = 50.0,
    evidence: EvidenceState = EvidenceState.CANDIDATE,
    same_cluster_open: bool = False,
    corr: float | None = None,
    cost_ratio: float | None = 1.0,
    cluster_util: float = 0.20,
    cost_headroom: float = 50.0,
    trigger_offset_s: int = 0,
) -> AllocationCandidate:
    return AllocationCandidate(
        ticket_id=ticket_id,
        route_id=route_id,
        trigger_bar_close_exchange_ts=T0 + timedelta(seconds=trigger_offset_s),
        ros_norm=ros,
        conservative_net_expectancy_after_25_cost=expectancy,
        closed_trade_count=n,
        evidence_state=evidence,
        operational_state=OperationalState.ENABLED,
        governor_state=GovernorState.NORMAL,
        runtime_eligible=True,
        has_open_same_cluster_exposure=same_cluster_open,
        mean_same_cluster_correlation=corr,
        execution_cost_ratio=cost_ratio,
        cluster_risk_utilization=cluster_util,
        cost_headroom_component=cost_headroom,
    )


def test_allocator_version_and_weights_are_frozen_f005_values() -> None:
    assert allocator_version() == "allocation_score_v1"
    assert dict(ALLOCATOR_WEIGHTS) == {
        "ros_norm": 0.45,
        "conservative_expectancy_score": 0.20,
        "evidence_quality_score": 0.15,
        "diversification_score": 0.10,
        "execution_quality_score": 0.10,
    }


def test_expectancy_percentiles_span_zero_to_100_and_middle_is_50() -> None:
    rows = (
        _candidate(ticket_id="low", route_id="a:intraday:long", expectancy=-1.0),
        _candidate(ticket_id="mid", route_id="b:intraday:long", expectancy=0.0),
        _candidate(ticket_id="high", route_id="c:intraday:long", expectancy=1.0),
    )
    by_id = {
        row.ticket_id: row
        for row in allocate_fire_batch(rows)
    }
    assert by_id["low"].conservative_expectancy_score == pytest.approx(0.0)
    assert by_id["mid"].conservative_expectancy_score == pytest.approx(50.0)
    assert by_id["high"].conservative_expectancy_score == pytest.approx(100.0)


def test_expectancy_ties_use_average_rank_and_single_candidate_is_neutral() -> None:
    tied = allocate_fire_batch(
        (
            _candidate(ticket_id="a", route_id="a:intraday:long", expectancy=1.0),
            _candidate(ticket_id="b", route_id="b:intraday:long", expectancy=1.0),
        )
    )
    assert {row.conservative_expectancy_score for row in tied} == {50.0}

    single = allocate_fire_batch(
        (_candidate(ticket_id="one", route_id="one:intraday:long"),)
    )
    assert single[0].conservative_expectancy_score == pytest.approx(50.0)
    assert single[0].allocation_order == 1


def test_less_than_15_or_missing_expectancy_is_neutral_50() -> None:
    rows = allocate_fire_batch(
        (
            _candidate(
                ticket_id="small",
                route_id="a:intraday:long",
                expectancy=99.0,
                n=14,
            ),
            _candidate(
                ticket_id="missing",
                route_id="b:intraday:long",
                expectancy=None,
                n=40,
            ),
            _candidate(
                ticket_id="usable",
                route_id="c:intraday:long",
                expectancy=1.0,
                n=30,
            ),
        )
    )
    by_id = {row.ticket_id: row for row in rows}
    assert by_id["small"].conservative_expectancy_score == 50.0
    assert by_id["missing"].conservative_expectancy_score == 50.0
    assert by_id["usable"].conservative_expectancy_score == 50.0


@pytest.mark.parametrize(
    ("state", "expected"),
    (
        (EvidenceState.KEEP_TRUSTED, 100.0),
        (EvidenceState.KEEP_PROBATION, 80.0),
        (EvidenceState.EVIDENCE_ACCUMULATING, 60.0),
        (EvidenceState.CANDIDATE, 50.0),
        (EvidenceState.CUT_SIZE, 20.0),
    ),
)
def test_evidence_quality_mapping_is_exact(
    state: EvidenceState,
    expected: float,
) -> None:
    out = allocate_fire_batch(
        (
            _candidate(
                ticket_id=state.value,
                route_id=f"{state.value}:intraday:long",
                evidence=state,
            ),
        )
    )[0]
    assert out.evidence_quality_score == expected


def test_bench_disabled_halt_and_noneligible_never_enter_allocator() -> None:
    base = dict(
        ticket_id="x",
        route_id="x:intraday:long",
        trigger_bar_close_exchange_ts=T0,
        ros_norm=50.0,
        conservative_net_expectancy_after_25_cost=1.0,
        closed_trade_count=30,
        has_open_same_cluster_exposure=False,
        mean_same_cluster_correlation=None,
        execution_cost_ratio=None,
        cluster_risk_utilization=0.0,
        cost_headroom_component=50.0,
    )
    with pytest.raises(ValueError, match="BENCH"):
        AllocationCandidate(
            **base,
            evidence_state=EvidenceState.BENCH,
            operational_state=OperationalState.ENABLED,
            governor_state=GovernorState.NORMAL,
            runtime_eligible=True,
        )
    with pytest.raises(ValueError, match="DISABLED"):
        AllocationCandidate(
            **base,
            evidence_state=EvidenceState.CANDIDATE,
            operational_state=OperationalState.DISABLED,
            governor_state=GovernorState.NORMAL,
            runtime_eligible=True,
        )
    with pytest.raises(ValueError, match="HALT"):
        AllocationCandidate(
            **base,
            evidence_state=EvidenceState.CANDIDATE,
            operational_state=OperationalState.ENABLED,
            governor_state=GovernorState.HALT,
            runtime_eligible=True,
        )
    with pytest.raises(ValueError, match="runtime eligible"):
        AllocationCandidate(
            **base,
            evidence_state=EvidenceState.CANDIDATE,
            operational_state=OperationalState.ENABLED,
            governor_state=GovernorState.NORMAL,
            runtime_eligible=False,
        )


@pytest.mark.parametrize(
    ("same_open", "corr", "score", "flag"),
    (
        (False, None, 100.0, None),
        (True, 0.49, 75.0, None),
        (True, 0.50, 50.0, None),
        (True, 0.75, 50.0, None),
        (True, None, 50.0, "correlation_unknown"),
    ),
)
def test_diversification_score_boundaries(
    same_open: bool,
    corr: float | None,
    score: float,
    flag: str | None,
) -> None:
    out = allocate_fire_batch(
        (
            _candidate(
                ticket_id="x",
                route_id="x:intraday:long",
                same_cluster_open=same_open,
                corr=corr,
            ),
        )
    )[0]
    assert out.diversification_score == score
    assert (flag in out.flags) if flag else not out.flags


def test_correlation_above_075_is_hard_block_before_scoring() -> None:
    with pytest.raises(ValueError, match="correlation hard block"):
        _candidate(
            ticket_id="x",
            route_id="x:intraday:long",
            same_cluster_open=True,
            corr=0.750001,
        )


@pytest.mark.parametrize(
    ("ratio", "score"),
    (
        (1.00, 100.0),
        (1.10, 80.0),
        (1.25, 60.0),
        (1.50, 30.0),
        (1.500001, 0.0),
    ),
)
def test_execution_quality_thresholds_are_exact(
    ratio: float,
    score: float,
) -> None:
    out = allocate_fire_batch(
        (
            _candidate(
                ticket_id="x",
                route_id="x:intraday:long",
                cost_ratio=ratio,
            ),
        )
    )[0]
    assert out.execution_quality_score == score


def test_unknown_execution_quality_is_neutral_and_flagged() -> None:
    out = allocate_fire_batch(
        (
            _candidate(
                ticket_id="x",
                route_id="x:intraday:long",
                cost_ratio=None,
            ),
        )
    )[0]
    assert out.execution_quality_score == 50.0
    assert out.flags == ("execution_quality_unknown",)


def test_exact_weighted_score() -> None:
    out = allocate_fire_batch(
        (
            _candidate(
                ticket_id="x",
                route_id="x:intraday:long",
                ros=80.0,
                expectancy=None,
                n=0,
                evidence=EvidenceState.KEEP_PROBATION,
                same_cluster_open=False,
                cost_ratio=1.20,
            ),
        )
    )[0]
    expected = (
        0.45 * 80.0
        + 0.20 * 50.0
        + 0.15 * 80.0
        + 0.10 * 100.0
        + 0.10 * 60.0
    )
    assert out.allocation_score_v1 == pytest.approx(expected)


def test_tie_breakers_apply_in_frozen_order_and_route_lexical_is_final() -> None:
    # All score components are intentionally equal. Expectancy and ROS also tie.
    # Then lower cluster utilization wins, then higher cost headroom, then earlier
    # trigger close, then route lexical.
    rows = (
        _candidate(
            ticket_id="route-b",
            route_id="b:intraday:long",
            expectancy=None,
            n=0,
            cluster_util=0.20,
            cost_headroom=50.0,
            trigger_offset_s=0,
        ),
        _candidate(
            ticket_id="route-a",
            route_id="a:intraday:long",
            expectancy=None,
            n=0,
            cluster_util=0.20,
            cost_headroom=50.0,
            trigger_offset_s=0,
        ),
        _candidate(
            ticket_id="earlier-util",
            route_id="z:intraday:long",
            expectancy=None,
            n=0,
            cluster_util=0.10,
            cost_headroom=10.0,
            trigger_offset_s=100,
        ),
    )
    ranked = allocate_fire_batch(rows)
    assert [row.ticket_id for row in ranked] == [
        "earlier-util",
        "route-a",
        "route-b",
    ]
    assert [row.allocation_order for row in ranked] == [1, 2, 3]


def test_allocator_decision_has_no_quantity_or_risk_authority_fields() -> None:
    out = allocate_fire_batch(
        (_candidate(ticket_id="x", route_id="x:intraday:long"),)
    )[0]
    assert not hasattr(out, "quantity")
    assert not hasattr(out, "risk_fraction")
    assert not hasattr(out, "reserve_usd")


def test_duplicate_ticket_or_route_in_same_batch_fails_closed() -> None:
    with pytest.raises(ValueError, match="duplicate ticket_id"):
        allocate_fire_batch(
            (
                _candidate(ticket_id="x", route_id="a:intraday:long"),
                _candidate(ticket_id="x", route_id="b:intraday:long"),
            )
        )
    with pytest.raises(ValueError, match="duplicate route_id"):
        allocate_fire_batch(
            (
                _candidate(ticket_id="x", route_id="a:intraday:long"),
                _candidate(ticket_id="y", route_id="a:intraday:long"),
            )
        )
