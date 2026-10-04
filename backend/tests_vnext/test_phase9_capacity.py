from __future__ import annotations

import pytest

from aether_vnext.capacity import CapacityEvidenceInput, assess_capacity


def _input(**overrides) -> CapacityEvidenceInput:
    values = dict(
        intended_quantity=10.0,
        expected_gross_edge_usd_per_trade=25.0,
        base_round_trip_cost_usd_per_trade=5.0,
        marginal_slippage_usd_per_trade=2.0,
        gap_tail_cost_usd_per_trade=1.0,
        spread_percentile=70.0,
        spread_readiness=True,
        depth_data_available=True,
        depth_capacity_quantity=20.0,
        conservative_product_cap_quantity=None,
        locate_required=False,
        locate_available=None,
        borrow_cost_required=False,
        borrow_cost_usd_per_trade=None,
        carry_cost_material=False,
        carry_cost_usd_per_trade=None,
    )
    values.update(overrides)
    return CapacityEvidenceInput(**values)


def test_intended_size_capacity_is_positive_only_after_all_bound_costs() -> None:
    out = assess_capacity(_input())
    assert out.applicable_capacity_quantity == pytest.approx(20.0)
    assert out.quantity_within_capacity is True
    assert out.total_modeled_cost_usd_per_trade == pytest.approx(8.0)
    assert out.intended_size_net_expectancy_usd == pytest.approx(17.0)
    assert out.economically_positive_at_intended_size is True
    assert out.trusted_keep_ready is True
    assert out.unresolved_inputs == ()
    assert out.blocking_reasons == ()


def test_small_size_edge_cannot_hide_negative_intended_size_economics() -> None:
    out = assess_capacity(
        _input(
            expected_gross_edge_usd_per_trade=7.0,
            marginal_slippage_usd_per_trade=2.0,
            gap_tail_cost_usd_per_trade=1.0,
        )
    )
    assert out.intended_size_net_expectancy_usd == pytest.approx(-1.0)
    assert out.economically_positive_at_intended_size is False
    assert out.trusted_keep_ready is False
    assert "intended_size_net_expectancy_not_positive" in out.blocking_reasons


def test_depth_or_conservative_product_cap_must_bound_intended_quantity() -> None:
    depth_blocked = assess_capacity(
        _input(depth_capacity_quantity=5.0)
    )
    assert depth_blocked.quantity_within_capacity is False
    assert "intended_quantity_exceeds_capacity" in depth_blocked.blocking_reasons

    fallback = assess_capacity(
        _input(
            depth_data_available=False,
            depth_capacity_quantity=None,
            conservative_product_cap_quantity=12.0,
        )
    )
    assert fallback.depth_status == "PRODUCT_CAP_BOUND"
    assert fallback.quantity_within_capacity is True
    assert fallback.trusted_keep_ready is True

    unresolved = assess_capacity(
        _input(
            depth_data_available=False,
            depth_capacity_quantity=None,
            conservative_product_cap_quantity=None,
        )
    )
    assert "conservative_product_cap_quantity_missing" in unresolved.unresolved_inputs
    assert unresolved.trusted_keep_ready is False


def test_short_locate_and_borrow_cost_fail_closed() -> None:
    locate = assess_capacity(
        _input(
            locate_required=True,
            locate_available=False,
        )
    )
    assert locate.locate_status == "UNAVAILABLE"
    assert "required_locate_unavailable" in locate.blocking_reasons
    assert locate.trusted_keep_ready is False

    borrow = assess_capacity(
        _input(
            locate_required=True,
            locate_available=True,
            borrow_cost_required=True,
            borrow_cost_usd_per_trade=None,
        )
    )
    assert borrow.borrow_status == "UNKNOWN"
    assert "required_borrow_cost_unknown" in borrow.unresolved_inputs
    assert borrow.trusted_keep_ready is False


def test_material_unknown_carry_blocks_trusted_keep() -> None:
    out = assess_capacity(
        _input(
            carry_cost_material=True,
            carry_cost_usd_per_trade=None,
        )
    )
    assert out.carry_status == "UNKNOWN_MATERIAL"
    assert "material_carry_cost_unknown" in out.unresolved_inputs
    assert out.trusted_keep_ready is False


def test_spread_percentile_is_retained_but_no_threshold_is_invented() -> None:
    unresolved = assess_capacity(
        _input(spread_readiness=None)
    )
    assert unresolved.spread_percentile == pytest.approx(70.0)
    assert "spread_readiness_policy_unbound" in unresolved.unresolved_inputs
    assert unresolved.trusted_keep_ready is False

    blocked = assess_capacity(
        _input(spread_readiness=False)
    )
    assert "spread_not_economically_ready" in blocked.blocking_reasons


def test_capacity_payload_matches_profitability_evidence_contract() -> None:
    payload = assess_capacity(_input()).as_evidence_payload()
    assert payload["trusted_keep_ready"] is True
    assert payload["intended_quantity"] == pytest.approx(10.0)
    assert payload["intended_size_net_expectancy_usd"] == pytest.approx(17.0)
    assert payload["locate_status"] == "NOT_REQUIRED"


def test_missing_slippage_or_gap_tail_cost_stays_explicit() -> None:
    out = assess_capacity(
        _input(
            marginal_slippage_usd_per_trade=None,
            gap_tail_cost_usd_per_trade=None,
        )
    )
    assert set(out.unresolved_inputs) >= {
        "marginal_slippage_curve_missing",
        "gap_tail_cost_missing",
    }
    assert out.total_modeled_cost_usd_per_trade is None
    assert out.trusted_keep_ready is False
