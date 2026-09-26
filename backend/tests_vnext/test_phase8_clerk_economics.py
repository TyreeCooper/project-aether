from __future__ import annotations

from dataclasses import replace

import pytest

from aether_vnext.clerk import (
    evaluate_clerk_ready,
    opportunity_and_exit_reference,
)
from aether_vnext.registry import SEED_REGISTRY, ShortabilityState


def test_target_based_opportunity_is_side_aware_and_percent_of_entry() -> None:
    long_pct, long_exit = opportunity_and_exit_reference(
        side="long",
        entry_reference_price=100.0,
        first_target_price=102.0,
        atr=None,
    )
    short_pct, short_exit = opportunity_and_exit_reference(
        side="short",
        entry_reference_price=100.0,
        first_target_price=98.0,
        atr=None,
    )
    assert long_pct == pytest.approx(2.0)
    assert short_pct == pytest.approx(2.0)
    assert long_exit == pytest.approx(102.0)
    assert short_exit == pytest.approx(98.0)


def test_no_target_uses_one_atr_from_entry_for_opportunity_and_cost_reference() -> None:
    pct, exit_reference = opportunity_and_exit_reference(
        side="long",
        entry_reference_price=100.0,
        first_target_price=None,
        atr=1.5,
    )
    assert pct == pytest.approx(1.5)
    assert exit_reference == pytest.approx(101.5)


@pytest.mark.parametrize(
    ("side", "target"),
    (("long", 99.0), ("short", 101.0)),
)
def test_nonfavorable_named_target_is_rejected(
    side: str,
    target: float,
) -> None:
    with pytest.raises(ValueError, match="not favorable"):
        opportunity_and_exit_reference(
            side=side,
            entry_reference_price=100.0,
            first_target_price=target,
            atr=None,
        )


def test_clerk_exact_costs_keep_zero_commission_fx_friction_nonzero() -> None:
    decision = evaluate_clerk_ready(
        SEED_REGISTRY["eurusd"],
        side="long",
        qty=0.10,
        entry_reference_price=1.1000,
        spread_abs=0.0002,
        first_target_price=1.1020,
        atr=None,
    )
    assert decision.costs is not None
    assert decision.costs.entry_fee_usd == 0.0
    assert decision.costs.exit_fee_usd == 0.0
    assert decision.costs.spread_usd > 0
    assert decision.costs.slip_usd > 0
    assert decision.modeled_round_trip_cost_pct > 0


def test_ready_hurdle_is_strict_and_clerk_never_changes_quantity() -> None:
    row = SEED_REGISTRY["btc"]
    decision = evaluate_clerk_ready(
        row,
        side="long",
        qty=0.01,
        entry_reference_price=100_000.0,
        spread_abs=20.0,
        first_target_price=102_000.0,
        atr=None,
    )
    assert decision.costs is not None
    assert decision.ready is (
        decision.opportunity_pct > decision.cost_hurdle_pct
    )
    assert not hasattr(decision, "quantity")


def test_cost_hurdle_failure_uses_canonical_clerk_reason() -> None:
    decision = evaluate_clerk_ready(
        SEED_REGISTRY["btc"],
        side="long",
        qty=0.01,
        entry_reference_price=100_000.0,
        spread_abs=100.0,
        first_target_price=100_100.0,
        atr=None,
    )
    assert decision.ready is False
    assert (
        decision.reject_code
        == "cost_hurdle_exceeds_expected_move"
    )


def test_equity_short_requires_available_shortability_and_locate() -> None:
    nvda = SEED_REGISTRY["nvda"]

    blocked = evaluate_clerk_ready(
        nvda,
        side="short",
        qty=10,
        entry_reference_price=100.0,
        spread_abs=0.02,
        first_target_price=95.0,
        atr=None,
        locate_ok=True,
        holding_days=1.0,
    )
    assert blocked.ready is False
    assert blocked.reject_code == "side_not_supported"
    assert blocked.costs is None

    available = replace(
        nvda,
        shortability_state=ShortabilityState.AVAILABLE,
    )
    no_locate = evaluate_clerk_ready(
        available,
        side="short",
        qty=10,
        entry_reference_price=100.0,
        spread_abs=0.02,
        first_target_price=95.0,
        atr=None,
        locate_ok=False,
        holding_days=1.0,
    )
    assert no_locate.reject_code == "side_not_supported"

    located = evaluate_clerk_ready(
        available,
        side="short",
        qty=10,
        entry_reference_price=100.0,
        spread_abs=0.02,
        first_target_price=95.0,
        atr=None,
        locate_ok=True,
        holding_days=1.0,
    )
    assert located.costs is not None
    assert located.costs.carry_or_borrow_usd > 0


def test_crypto_short_is_blocked_by_current_product_truth() -> None:
    decision = evaluate_clerk_ready(
        SEED_REGISTRY["btc"],
        side="short",
        qty=0.01,
        entry_reference_price=100_000.0,
        spread_abs=20.0,
        first_target_price=95_000.0,
        atr=None,
    )
    assert decision.ready is False
    assert decision.reject_code == "side_not_supported"
    assert decision.costs is None


def test_cost_edge_multiple_may_raise_but_not_fall_below_one() -> None:
    raised = evaluate_clerk_ready(
        SEED_REGISTRY["eurusd"],
        side="long",
        qty=0.10,
        entry_reference_price=1.1000,
        spread_abs=0.0002,
        first_target_price=1.1020,
        atr=None,
        cost_edge_multiple=1.50,
    )
    assert raised.costs is not None
    assert raised.costs.cost_edge_multiple == pytest.approx(1.50)

    invalid = evaluate_clerk_ready(
        SEED_REGISTRY["eurusd"],
        side="long",
        qty=0.10,
        entry_reference_price=1.1000,
        spread_abs=0.0002,
        first_target_price=1.1020,
        atr=None,
        cost_edge_multiple=0.99,
    )
    assert invalid.ready is False
    assert invalid.reject_code == "product_cost_model_error"


def test_cost_headroom_score_matches_source_formula_and_clips() -> None:
    decision = evaluate_clerk_ready(
        SEED_REGISTRY["eurusd"],
        side="long",
        qty=0.10,
        entry_reference_price=1.1000,
        spread_abs=0.0002,
        first_target_price=1.1020,
        atr=None,
    )
    assert decision.costs is not None
    expected = max(
        0.0,
        min(
            100.0,
            100.0
            * (
                decision.opportunity_pct
                - decision.costs.cost_hurdle_pct
            )
            / decision.opportunity_pct,
        ),
    )
    assert decision.cost_headroom_score == pytest.approx(expected)


def test_missing_atr_for_no_target_fails_closed() -> None:
    with pytest.raises(ValueError, match="ATR is required"):
        evaluate_clerk_ready(
            SEED_REGISTRY["eurusd"],
            side="long",
            qty=0.10,
            entry_reference_price=1.1000,
            spread_abs=0.0002,
            first_target_price=None,
            atr=None,
        )
