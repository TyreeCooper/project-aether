from __future__ import annotations

import pytest

from aether_vnext.registry import SEED_REGISTRY
from aether_vnext.risk import (
    BookRiskPosition,
    RiskExposure,
    aggregate_book_risk,
    size_candidate_to_risk,
)


def test_cost_aware_sizing_uses_stop_plus_estimated_round_trip_per_unit() -> None:
    result = size_candidate_to_risk(
        SEED_REGISTRY["eurusd"],
        side="long",
        entry_price=1.1000,
        stop_price=1.0950,
        equity_usd=10_000.0,
        estimated_round_trip_cost_per_unit_usd=50.0,
    )
    assert result.ok is True
    assert result.quantity == pytest.approx(0.13)
    assert result.stop_risk_usd == pytest.approx(65.0)
    assert result.estimated_round_trip_cost_usd == pytest.approx(6.5)
    assert result.modeled_loss_at_stop_usd == pytest.approx(71.5)
    assert result.modeled_loss_at_stop_usd <= result.allowed_risk_usd


def test_eth_hitch_can_be_tighter_than_primary_asset_budget() -> None:
    result = size_candidate_to_risk(
        SEED_REGISTRY["eth"],
        side="long",
        entry_price=4_000.0,
        stop_price=3_900.0,
        equity_usd=10_000.0,
        asset_risk_hitches={"btc": 0.50},
        cross_asset_remaining_risk_usd={"btc": 10.0},
    )
    assert result.ok is True
    assert result.quantity == pytest.approx(0.20)
    assert result.stop_risk_usd == pytest.approx(20.0)
    assert dict(result.asset_risk_hitches_usd) == pytest.approx({"btc": 10.0})


def test_hitch_missing_target_capacity_fails_closed() -> None:
    with pytest.raises(ValueError, match="missing remaining asset-risk capacity"):
        size_candidate_to_risk(
            SEED_REGISTRY["eth"],
            side="long",
            entry_price=4_000.0,
            stop_price=3_900.0,
            equity_usd=10_000.0,
            asset_risk_hitches={"btc": 0.50},
        )


def test_open_book_hitch_hits_asset_only_not_cluster_or_portfolio_twice() -> None:
    snapshot = aggregate_book_risk(
        (
            BookRiskPosition(
                trade_id="eth-trade",
                position_key="eth:daily_swing",
                asset_id="eth",
                cluster_id="crypto",
                stop_risk_usd=40.0,
                asset_risk_hitches_usd=(("btc", 20.0),),
            ),
        )
    )
    by_asset = {row.key: row.stop_risk_usd for row in snapshot.by_asset}
    by_cluster = {row.key: row.stop_risk_usd for row in snapshot.by_cluster}
    assert by_asset == pytest.approx({"eth": 40.0, "btc": 20.0})
    assert by_cluster == pytest.approx({"crypto": 40.0})
    assert snapshot.portfolio_open_risk_usd == pytest.approx(40.0)


def test_primary_asset_and_cross_asset_constraints_both_apply() -> None:
    result = size_candidate_to_risk(
        SEED_REGISTRY["eth"],
        side="long",
        entry_price=4_000.0,
        stop_price=3_900.0,
        equity_usd=10_000.0,
        exposure=RiskExposure(asset_open_risk_usd=130.0),
        asset_risk_hitches={"btc": 0.50},
        cross_asset_remaining_risk_usd={"btc": 100.0},
    )
    assert result.ok is True
    assert result.stop_risk_usd <= 20.0 + 1e-9
