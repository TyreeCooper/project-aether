from __future__ import annotations

import pytest

from aether_vnext.research_integrity import (
    ResearchIntegrityPolicy,
    ResearchIntegrityTrade,
    assess_research_integrity,
)


def _trade(
    trade_id: str,
    *,
    episode_id: str,
    pnl: float,
    regime: str = "trend",
    domain: str = "held_out",
) -> ResearchIntegrityTrade:
    return ResearchIntegrityTrade(
        trade_id=trade_id,
        episode_id=episode_id,
        sample_domain=domain,
        net_pnl_usd=pnl,
        regime_label=regime,
    )


def test_unbound_thresholds_are_reported_not_invented() -> None:
    assessment = assess_research_integrity(
        (
            _trade("t1", episode_id="e1", pnl=10.0),
            _trade("t2", episode_id="e2", pnl=-2.0, regime="range"),
        ),
        parameter_variant_count=2,
    )

    assert assessment.status == "UNBOUND_POLICY"
    assert assessment.flags == ()
    assert assessment.independent_n == 2
    assert set(assessment.unresolved_rules) == {
        "parameter_mining_threshold_unbound",
        "sample_starvation_threshold_unbound",
        "outlier_dependence_threshold_unbound",
        "regime_concentration_threshold_unbound",
    }


def test_replayed_episode_does_not_increase_independent_n() -> None:
    policy = ResearchIntegrityPolicy(
        minimum_independent_n=2,
        max_parameter_variants=10,
        max_largest_trade_share=1.0,
        max_top_decile_trade_share=1.0,
        max_regime_share=1.0,
    )
    assessment = assess_research_integrity(
        (
            _trade("replay-1", episode_id="episode-a", pnl=1.0),
            _trade("replay-2", episode_id="episode-a", pnl=1.0),
        ),
        parameter_variant_count=1,
        policy=policy,
    )

    assert assessment.trade_count == 2
    assert assessment.independent_n == 1
    assert assessment.status == "FLAGGED"
    assert assessment.flags == ("sample_starvation",)


def test_bound_policy_detects_all_required_integrity_failure_modes() -> None:
    policy = ResearchIntegrityPolicy(
        minimum_independent_n=5,
        max_parameter_variants=3,
        max_largest_trade_share=0.60,
        max_top_decile_trade_share=0.60,
        max_regime_share=0.75,
    )
    assessment = assess_research_integrity(
        (
            _trade("t1", episode_id="e1", pnl=90.0),
            _trade("t2", episode_id="e2", pnl=5.0),
            _trade("t3", episode_id="e3", pnl=5.0),
            _trade("t4", episode_id="e4", pnl=-10.0),
        ),
        parameter_variant_count=8,
        policy=policy,
    )

    assert assessment.status == "FLAGGED"
    assert assessment.unresolved_rules == ()
    assert set(assessment.flags) == {
        "parameter_mining",
        "sample_starvation",
        "outlier_dependence",
        "regime_concentration",
    }
    assert assessment.largest_trade_share_of_positive_pnl == pytest.approx(0.90)
    assert assessment.max_regime_trade_share == pytest.approx(1.0)


def test_bound_clear_sample_remains_observational_only() -> None:
    policy = ResearchIntegrityPolicy(
        minimum_independent_n=4,
        max_parameter_variants=4,
        max_largest_trade_share=0.40,
        max_top_decile_trade_share=0.40,
        max_regime_share=0.50,
    )
    assessment = assess_research_integrity(
        (
            _trade("t1", episode_id="e1", pnl=25.0, regime="trend"),
            _trade("t2", episode_id="e2", pnl=25.0, regime="trend"),
            _trade("t3", episode_id="e3", pnl=25.0, regime="range"),
            _trade("t4", episode_id="e4", pnl=25.0, regime="range"),
        ),
        parameter_variant_count=2,
        policy=policy,
    )

    assert assessment.status == "CLEAR"
    assert assessment.flags == ()
    assert assessment.unresolved_rules == ()


def test_mixed_sample_domains_are_rejected() -> None:
    with pytest.raises(ValueError, match="cannot mix sample domains"):
        assess_research_integrity(
            (
                _trade("t1", episode_id="e1", pnl=1.0, domain="held_out"),
                _trade("t2", episode_id="e2", pnl=1.0, domain="paper_forward"),
            ),
            parameter_variant_count=1,
        )


def test_duplicate_trade_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate trade_id"):
        assess_research_integrity(
            (
                _trade("same", episode_id="e1", pnl=1.0),
                _trade("same", episode_id="e2", pnl=1.0),
            ),
            parameter_variant_count=1,
        )


def test_integrity_trade_rejects_boolean_pnl() -> None:
    with pytest.raises(
        ValueError,
        match="net_pnl_usd must be numeric, not boolean",
    ):
        _trade("t1", episode_id="e1", pnl=True)


@pytest.mark.parametrize(
    "field",
    (
        "max_largest_trade_share",
        "max_top_decile_trade_share",
        "max_regime_share",
    ),
)
def test_integrity_policy_rejects_boolean_ratio_thresholds(field: str) -> None:
    kwargs = {
        "minimum_independent_n": 1,
        "max_parameter_variants": 1,
        "max_largest_trade_share": 1.0,
        "max_top_decile_trade_share": 1.0,
        "max_regime_share": 1.0,
    }
    kwargs[field] = True

    with pytest.raises(ValueError, match="numeric, not boolean"):
        ResearchIntegrityPolicy(**kwargs)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("minimum_independent_n", 0),
        ("max_parameter_variants", True),
        ("max_largest_trade_share", 1.1),
        ("max_top_decile_trade_share", -0.1),
        ("max_regime_share", float("inf")),
    ),
)
def test_invalid_policy_thresholds_are_rejected(field: str, value: object) -> None:
    kwargs = {
        "minimum_independent_n": 1,
        "max_parameter_variants": 1,
        "max_largest_trade_share": 1.0,
        "max_top_decile_trade_share": 1.0,
        "max_regime_share": 1.0,
    }
    kwargs[field] = value
    with pytest.raises(ValueError):
        ResearchIntegrityPolicy(**kwargs)
