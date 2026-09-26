from __future__ import annotations

import pytest

from aether_vnext.freeze import EvidenceState
from aether_vnext.review import (
    CUT_SIZE_FLOOR_FRACTION,
    ReviewGateInput,
    assess_review_gates,
    validate_review_verdict,
)


def _gate(**overrides) -> ReviewGateInput:
    values = dict(
        evidence_id="e1",
        n_closed=20,
        fold_expectancy_after_plus25_cost=(1.0, 1.0, 1.0),
        expectancy_ci_lower=0.0,
        net_expectancy_after_costs=1.0,
        profit_factor=1.25,
        stop_rate=0.40,
        baseline_not_worse=True,
        folds_chronological=True,
        integrity_clear=True,
        current_route_risk_fraction=0.0075,
        radar_eligible_routes=12,
        prior_evidence_state=EvidenceState.CANDIDATE,
        false_discovery_extra_fold_completed=False,
        multi_day_fx=False,
        carry_model_present=True,
        capacity_trusted_keep_ready=True,
        last10_stop_grind_confirmed=False,
    )
    values.update(overrides)
    return ReviewGateInput(**values)


def test_probation_keep_gate_is_exact_and_no_keep_below_15() -> None:
    good = assess_review_gates(_gate(n_closed=15))
    assert good.probation_keep_eligible is True
    validate_review_verdict(good, EvidenceState.KEEP_PROBATION)

    too_small = assess_review_gates(_gate(n_closed=14))
    assert too_small.probation_keep_eligible is False
    with pytest.raises(ValueError, match="KEEP_PROBATION"):
        validate_review_verdict(
            too_small, EvidenceState.KEEP_PROBATION
        )

    negative_ci = assess_review_gates(
        _gate(expectancy_ci_lower=-0.000001)
    )
    assert negative_ci.probation_keep_eligible is False

    two_folds = assess_review_gates(
        _gate(fold_expectancy_after_plus25_cost=(1.0, 1.0))
    )
    assert two_folds.probation_keep_eligible is False


def test_trusted_keep_requires_all_source_bars() -> None:
    good = assess_review_gates(
        _gate(
            n_closed=30,
            fold_expectancy_after_plus25_cost=(
                1.0, 1.0, 1.0, -1.0
            ),
            profit_factor=1.200001,
            stop_rate=0.549999,
        )
    )
    assert good.positive_plus25_fold_count == 3
    assert good.trusted_keep_eligible is True
    validate_review_verdict(good, EvidenceState.KEEP_TRUSTED)

    assert assess_review_gates(
        _gate(
            n_closed=29,
            fold_expectancy_after_plus25_cost=(1,1,1,1),
        )
    ).trusted_keep_eligible is False
    assert assess_review_gates(
        _gate(
            n_closed=30,
            fold_expectancy_after_plus25_cost=(1,1,-1,-1),
        )
    ).trusted_keep_eligible is False
    assert assess_review_gates(
        _gate(
            n_closed=30,
            fold_expectancy_after_plus25_cost=(1,1,1,1),
            profit_factor=1.20,
        )
    ).trusted_keep_eligible is False
    assert assess_review_gates(
        _gate(
            n_closed=30,
            fold_expectancy_after_plus25_cost=(1,1,1,1),
            stop_rate=0.55,
        )
    ).trusted_keep_eligible is False
    assert assess_review_gates(
        _gate(
            n_closed=30,
            fold_expectancy_after_plus25_cost=(1,1,1,1),
            baseline_not_worse=False,
        )
    ).trusted_keep_eligible is False


def test_false_discovery_over_50_requires_probation_plus_extra_fold_control() -> None:
    blocked = assess_review_gates(
        _gate(
            n_closed=30,
            fold_expectancy_after_plus25_cost=(1,1,1,1),
            radar_eligible_routes=51,
            prior_evidence_state=EvidenceState.CANDIDATE,
            false_discovery_extra_fold_completed=False,
        )
    )
    assert blocked.trusted_keep_eligible is False
    assert "false_discovery_control_unsatisfied" in blocked.reasons

    allowed = assess_review_gates(
        _gate(
            n_closed=30,
            fold_expectancy_after_plus25_cost=(1,1,1,1,1),
            radar_eligible_routes=51,
            prior_evidence_state=EvidenceState.KEEP_PROBATION,
            false_discovery_extra_fold_completed=True,
        )
    )
    assert allowed.trusted_keep_eligible is True


@pytest.mark.parametrize(
    ("expectancy", "stop_rate", "expected_reason"),
    (
        (1.0, 0.60, "n10_stop_rate_ge_0_60"),
        (0.0, 0.40, "n10_expectancy_le_0"),
    ),
)
def test_cut_size_exact_triggers_and_half_to_floor(
    expectancy: float,
    stop_rate: float,
    expected_reason: str,
) -> None:
    out = assess_review_gates(
        _gate(
            n_closed=10,
            net_expectancy_after_costs=expectancy,
            stop_rate=stop_rate,
            current_route_risk_fraction=0.0075,
        )
    )
    assert out.mandatory_state is EvidenceState.CUT_SIZE
    assert out.cut_size_fraction == pytest.approx(0.00375)
    assert expected_reason in out.reasons
    validate_review_verdict(out, EvidenceState.CUT_SIZE)

    floor = assess_review_gates(
        _gate(
            n_closed=10,
            stop_rate=0.60,
            current_route_risk_fraction=0.0030,
        )
    )
    assert floor.cut_size_fraction == pytest.approx(
        CUT_SIZE_FLOOR_FRACTION
    )


def test_negative_expectancy_bench_overrides_cut_size_at_n10() -> None:
    out = assess_review_gates(
        _gate(
            n_closed=10,
            net_expectancy_after_costs=-0.01,
        )
    )
    assert out.mandatory_state is EvidenceState.BENCH
    assert out.cut_size_fraction is None
    assert "n10_negative_expectancy_after_costs" in out.reasons
    validate_review_verdict(out, EvidenceState.BENCH)
    with pytest.raises(ValueError, match="must be BENCH"):
        validate_review_verdict(out, EvidenceState.CUT_SIZE)


def test_missing_carry_model_benches_multi_day_fx_even_below_n10() -> None:
    out = assess_review_gates(
        _gate(
            n_closed=4,
            multi_day_fx=True,
            carry_model_present=False,
        )
    )
    assert out.mandatory_state is EvidenceState.BENCH
    assert "multi_day_fx_missing_carry_model" in out.reasons


def test_source_unbound_stop_grind_tolerance_is_not_invented() -> None:
    unresolved = assess_review_gates(
        _gate(last10_stop_grind_confirmed=None)
    )
    assert "stop_grind_approximation_tolerance_unbound" in (
        unresolved.unresolved_rules
    )
    assert unresolved.mandatory_state is None

    confirmed = assess_review_gates(
        _gate(last10_stop_grind_confirmed=True)
    )
    assert confirmed.mandatory_state is EvidenceState.BENCH
    assert "last10_stop_grind_8_of_10" in confirmed.reasons


def test_mandatory_demotion_cannot_be_bypassed_by_accumulating_state() -> None:
    out = assess_review_gates(
        _gate(n_closed=10, stop_rate=0.60)
    )
    with pytest.raises(ValueError, match="must be CUT_SIZE"):
        validate_review_verdict(
            out, EvidenceState.EVIDENCE_ACCUMULATING
        )


def test_review_may_remain_conservative_without_auto_promotion() -> None:
    out = assess_review_gates(
        _gate(
            n_closed=30,
            fold_expectancy_after_plus25_cost=(1,1,1,1),
        )
    )
    assert out.trusted_keep_eligible is True
    validate_review_verdict(
        out, EvidenceState.EVIDENCE_ACCUMULATING
    )


def test_nonchronological_or_integrity_defect_blocks_keep() -> None:
    nonchron = assess_review_gates(
        _gate(
            n_closed=30,
            fold_expectancy_after_plus25_cost=(1,1,1,1),
            folds_chronological=False,
        )
    )
    assert nonchron.probation_keep_eligible is False
    assert nonchron.trusted_keep_eligible is False

    bad_integrity = assess_review_gates(
        _gate(
            n_closed=30,
            fold_expectancy_after_plus25_cost=(1,1,1,1),
            integrity_clear=False,
        )
    )
    assert bad_integrity.probation_keep_eligible is False
    assert bad_integrity.trusted_keep_eligible is False


def test_trusted_keep_is_blocked_when_intended_size_capacity_is_not_ready() -> None:
    out = assess_review_gates(
        _gate(
            n_closed=30,
            fold_expectancy_after_plus25_cost=(1, 1, 1, 1),
            capacity_trusted_keep_ready=False,
        )
    )
    assert out.trusted_keep_eligible is False
    assert "capacity_not_ready_for_trusted_keep" in out.reasons
    with pytest.raises(ValueError, match="KEEP_TRUSTED"):
        validate_review_verdict(out, EvidenceState.KEEP_TRUSTED)
