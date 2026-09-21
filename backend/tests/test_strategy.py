from app.strategy import (
    atr,
    crossover_signal,
    efficiency_ratio,
    exit_plan,
    resample_bars,
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
    assert crossover_signal([3, 2, 1, 2], 2, 3, False) == "buy"
    assert crossover_signal([1, 2, 3, 2], 2, 3, True) == "sell"


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
    assert cost >= 0.62


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
