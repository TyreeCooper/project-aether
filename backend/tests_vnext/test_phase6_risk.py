from __future__ import annotations

import pytest

from aether_vnext.freeze import (
    ASSET_RISK_FRACTION,
    CLUSTER_RISK_FRACTION,
    PORTFOLIO_RISK_FRACTION,
    TRADE_RISK_FRACTION,
)
from aether_vnext.reason_codes import ReasonCode
from aether_vnext.registry import SEED_REGISTRY
from aether_vnext.risk import (
    RiskExposure,
    RiskPolicy,
    floor_quantity_to_step,
    risk_limits_usd,
    size_candidate_to_risk,
    stop_risk_usd,
)


def test_constitutional_limits_on_seed_firm_equity() -> None:
    limits = risk_limits_usd(10_000.0)
    assert limits.trade_usd == pytest.approx(75.0)
    assert limits.asset_usd == pytest.approx(150.0)
    assert limits.cluster_usd == pytest.approx(225.0)
    assert limits.portfolio_usd == pytest.approx(300.0)


def test_policy_may_reduce_but_not_expand_constitutional_ceiling() -> None:
    reduced = RiskPolicy(
        trade_fraction=TRADE_RISK_FRACTION / 2,
        asset_fraction=ASSET_RISK_FRACTION / 2,
        cluster_fraction=CLUSTER_RISK_FRACTION / 2,
        portfolio_fraction=PORTFOLIO_RISK_FRACTION / 2,
    )
    assert risk_limits_usd(10_000.0, policy=reduced).trade_usd == pytest.approx(
        37.5
    )

    with pytest.raises(ValueError, match="constitutional ceiling"):
        RiskPolicy(trade_fraction=TRADE_RISK_FRACTION + 0.0001)


def test_stop_risk_uses_product_correct_fx_math() -> None:
    risk = stop_risk_usd(
        SEED_REGISTRY["eurusd"],
        side="long",
        quantity=0.10,
        entry_price=1.1000,
        stop_price=1.0950,
    )
    assert risk == pytest.approx(50.0)


def test_bad_stop_geometry_is_rejected_without_creating_size() -> None:
    result = size_candidate_to_risk(
        SEED_REGISTRY["nvda"],
        side="long",
        entry_price=100.0,
        stop_price=101.0,
        equity_usd=10_000.0,
    )
    assert result.ok is False
    assert result.reject_code == ReasonCode.BAD_STOP.value


def test_quantity_is_rounded_down_before_final_risk_check() -> None:
    result = size_candidate_to_risk(
        SEED_REGISTRY["eurusd"],
        side="long",
        entry_price=1.1000,
        stop_price=1.0951,
        equity_usd=10_000.0,
    )
    assert result.ok is True
    assert result.quantity == pytest.approx(0.15)
    assert result.stop_risk_usd == pytest.approx(73.5)
    assert result.stop_risk_usd <= result.limits.trade_usd


def test_asset_capacity_can_reduce_candidate_below_trade_budget() -> None:
    result = size_candidate_to_risk(
        SEED_REGISTRY["eurusd"],
        side="long",
        entry_price=1.1000,
        stop_price=1.0950,
        equity_usd=10_000.0,
        exposure=RiskExposure(asset_open_risk_usd=100.0),
    )
    assert result.ok is True
    assert result.allowed_risk_usd == pytest.approx(50.0)
    assert result.quantity == pytest.approx(0.10)
    assert result.stop_risk_usd == pytest.approx(50.0)


def test_full_asset_cluster_and_portfolio_capacity_have_canonical_reasons() -> None:
    asset = size_candidate_to_risk(
        SEED_REGISTRY["nvda"],
        side="long",
        entry_price=100.0,
        stop_price=95.0,
        equity_usd=10_000.0,
        exposure=RiskExposure(asset_open_risk_usd=150.0),
    )
    assert asset.reject_code == ReasonCode.ASSET_RISK_FULL.value

    cluster = size_candidate_to_risk(
        SEED_REGISTRY["nvda"],
        side="long",
        entry_price=100.0,
        stop_price=95.0,
        equity_usd=10_000.0,
        exposure=RiskExposure(cluster_open_risk_usd=225.0),
    )
    assert cluster.reject_code == ReasonCode.CLUSTER_RISK_FULL.value

    portfolio = size_candidate_to_risk(
        SEED_REGISTRY["nvda"],
        side="long",
        entry_price=100.0,
        stop_price=95.0,
        equity_usd=10_000.0,
        exposure=RiskExposure(portfolio_open_risk_usd=300.0),
    )
    assert portfolio.reject_code == ReasonCode.PORTFOLIO_RISK_FULL.value


def test_product_or_external_cap_can_only_reduce_risk_derived_quantity() -> None:
    uncapped = size_candidate_to_risk(
        SEED_REGISTRY["nvda"],
        side="long",
        entry_price=100.0,
        stop_price=95.0,
        equity_usd=10_000.0,
    )
    capped = size_candidate_to_risk(
        SEED_REGISTRY["nvda"],
        side="long",
        entry_price=100.0,
        stop_price=95.0,
        equity_usd=10_000.0,
        firm_capital_cap_qty=5.0,
    )
    assert uncapped.ok is True
    assert capped.ok is True
    assert capped.quantity <= uncapped.quantity
    assert capped.stop_risk_usd <= uncapped.stop_risk_usd


def test_minimum_quantity_that_cannot_fit_is_too_small() -> None:
    result = size_candidate_to_risk(
        SEED_REGISTRY["mes"],
        side="long",
        entry_price=6000.0,
        stop_price=5990.0,
        equity_usd=1_000.0,
    )
    assert result.ok is False
    assert result.reject_code == ReasonCode.TOO_SMALL.value


def test_decimal_step_floor_never_rounds_up() -> None:
    assert floor_quantity_to_step(0.159999999, 0.01) == pytest.approx(0.15)
    assert floor_quantity_to_step(7.99, 1.0) == pytest.approx(7.0)
