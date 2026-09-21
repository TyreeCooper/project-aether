from app.strategy import (
    atr,
    crossover_signal,
    efficiency_ratio,
    exit_plan,
    multi_horizon_momentum,
    resample_bars,
    risk_capped_qty,
    round_trip_cost_pct,
    sma,
    trend_breakout_snapshot,
)


def _bars(count=400, start=100.0, step=0.1):
    out = []
    px = start
    for i in range(count):
        px += step
        out.append(
            {
                "ts": 1_700_000_000 + i * 60,
                "open": px - step / 2,
                "high": px + 0.05,
                "low": px - 0.05,
                "close": px,
                "volume": 1.0,
            }
        )
    return out


def test_sma():
    assert sma([1, 2, 3, 4], 4) == 2.5
    assert sma([1, 2], 3) is None


def test_no_signal_when_warming():
    assert crossover_signal([1, 2, 3], 8, 21, False) is None


def test_cross_up_and_cross_down():
    assert crossover_signal([3, 1, 1, 3], 2, 3, False) == "buy"
    assert crossover_signal([1, 3, 3, 1], 2, 3, True) == "sell"


def test_resample_bars_aligns_timeframes():
    bars = _bars(15)
    assert len(resample_bars(bars, 5)) >= 3
    assert len(resample_bars(bars, 15)) >= 1


def test_efficiency_distinguishes_trend_from_chop():
    trend = list(range(20))
    chop = [100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100]
    assert efficiency_ratio(trend, 10) == 1.0
    assert efficiency_ratio(chop, 10) < 0.2


def test_cost_model_includes_round_trip_fees_and_slip():
    cost = round_trip_cost_pct(100, 99.99, 100.01)
    assert cost >= 1.70


def test_atr_and_exit_plan_are_finite():
    bars = _bars(50)
    assert atr(bars, 14) is not None
    plan = exit_plan(bars, 100, 103, 102, 2.0, 0.62)
    assert plan["active_stop"] > 0
    assert plan["active_stop"] < 103


def test_trend_breakout_rejects_flat_market():
    bars = _bars(420, start=100, step=0.0)
    snap = trend_breakout_snapshot(
        bars,
        mark=100,
        bid=99.99,
        ask=100.01,
    )
    assert snap["signal"] is None
    assert snap["reason"] in {
        "higher_timeframe_not_up",
        "local_trend_not_up",
        "low_efficiency",
        "no_breakout",
    }


def test_complete_resample_drops_partial_bucket():
    bars = [
        {"ts": 1_700_000_100 + i * 60, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1}
        for i in range(6)
    ]
    partial_ok = resample_bars(bars, 5, require_complete=False)
    complete = resample_bars(bars, 5, require_complete=True)
    assert len(partial_ok) >= len(complete)
    assert all(row["ts"] % 300 == 0 for row in complete)


def test_multi_horizon_momentum_votes():
    closes = [100 + i * 0.2 for i in range(80)]
    out = multi_horizon_momentum(closes)
    assert out["momentum_confirmed"] is True
    assert out["momentum_votes"] >= 2


def test_risk_cap_never_increases_configured_size():
    qty = risk_capped_qty(
        equity=10_000,
        price=100_000,
        configured_qty=0.01,
        stop_pct=2.0,
        cost_pct=1.7,
    )
    assert 0 < qty <= 0.01


def test_trend_snapshot_uses_completed_higher_timeframe_bars():
    bars = _bars(500, start=100, step=0.1)
    snap = trend_breakout_snapshot(
        bars,
        breakout_bars=20,
        mark=150,
        bid=149.99,
        ask=150.01,
        fee_rate=0.008,
    )
    assert snap["bars_5m"] <= len(bars) // 5
    assert snap["bars_15m"] <= len(bars) // 15


def test_round_trip_cost_matches_conservative_tier_one_fee():
    cost = round_trip_cost_pct(
        100.0,
        100.0,
        100.0,
        fee_rate=0.008,
        slippage_bps=5.0,
    )
    assert round(cost, 2) == 1.70
