from __future__ import annotations

from aether_vnext.market_fabric_microstructure import (
    BookLevel,
    TradePrint,
    build_microstructure_snapshot,
)


def test_microstructure_snapshot_derives_non_executable_features() -> None:
    snapshot = build_microstructure_snapshot(
        bid=100.0,
        ask=101.0,
        bids=(BookLevel(100.0, 5.0), BookLevel(99.5, 3.0)),
        asks=(BookLevel(101.0, 2.0), BookLevel(101.5, 2.0)),
        trades=(
            TradePrint(100.5, 2.0, "BUY"),
            TradePrint(100.4, 1.0, "SELL"),
        ),
        quote_timestamps_ms=(0, 100, 250, 500),
        mid_history=(100.0, 100.2, 100.1, 100.3),
        velocity_window_ms=1000,
        impact_notional=500.0,
    )

    assert snapshot.executable is False
    assert snapshot.spread_abs == 1.0
    assert snapshot.spread_bps is not None
    assert snapshot.depth_imbalance is not None
    assert snapshot.depth_imbalance > 0
    assert snapshot.trade_imbalance == (2.0 - 1.0) / 3.0
    assert snapshot.quote_velocity_hz is not None
    assert snapshot.realized_volatility is not None
    assert snapshot.liquidity_score is not None
    assert snapshot.market_impact_proxy_bps is not None


def test_missing_executable_book_does_not_invent_spread() -> None:
    snapshot = build_microstructure_snapshot(
        bid=None,
        ask=None,
        bids=(),
        asks=(),
        trades=(),
        quote_timestamps_ms=(),
        mid_history=(),
        velocity_window_ms=1000,
        impact_notional=100.0,
    )

    assert snapshot.spread_abs is None
    assert snapshot.spread_bps is None
    assert snapshot.liquidity_score is None
    assert snapshot.market_impact_proxy_bps is None


def test_unknown_aggressor_does_not_manufacture_trade_imbalance() -> None:
    snapshot = build_microstructure_snapshot(
        bid=100.0,
        ask=100.5,
        bids=(BookLevel(100.0, 1.0),),
        asks=(BookLevel(100.5, 1.0),),
        trades=(TradePrint(100.25, 1.0, None),),
        quote_timestamps_ms=(0, 100),
        mid_history=(100.0, 100.1, 100.2),
        velocity_window_ms=1000,
        impact_notional=100.0,
    )

    assert snapshot.trade_imbalance is None
