from app.clock import (HorizonController, allow_after_losses, close_in_upper_third, due_horizons, horizon_bucket, is_new_five_minute)
from app.horizons import TradingHorizon

def test_five_minute_edge():
    bars = [{"ts": 300, "close": 1}]
    fresh, bucket = is_new_five_minute(bars, None)
    assert not fresh and bucket == 300
    again, same = is_new_five_minute(bars, bucket)
    assert not again and same == 300
    nxt, new_bucket = is_new_five_minute([{"ts": 600, "close": 1}], bucket)
    assert nxt and new_bucket == 600

def test_horizon_bucket_alignment():
    assert horizon_bucket(599, TradingHorizon.INTRADAY) == 300
    assert horizon_bucket(3601, TradingHorizon.SWING) == 3600
    assert horizon_bucket(86499, TradingHorizon.POSITION) == 86400

def test_controller_waits_for_close_and_is_idempotent():
    clock = HorizonController()
    assert clock.due(300) == (TradingHorizon.SCALP,)
    due = clock.due(540)
    assert TradingHorizon.INTRADAY in due and TradingHorizon.SCALP in due
    assert clock.due(540) == ()

def test_controller_releases_multiple_horizons_together():
    due = HorizonController().due(3540)
    assert TradingHorizon.SCALP in due
    assert TradingHorizon.INTRADAY in due
    assert TradingHorizon.SWING in due
    assert TradingHorizon.HFT not in due

def test_controller_respects_registry_gate():
    assert TradingHorizon.HFT not in HorizonController().due(60)
    assert TradingHorizon.HFT in HorizonController().due(60, include_gated=True)

def test_due_horizons_restores_state_without_double_fire():
    due, state = due_horizons(540)
    assert TradingHorizon.INTRADAY in due
    again, _ = due_horizons(540, state)
    assert again == ()

def test_loss_sit_needs_15m_high():
    bars = []
    px = 100.0
    for i in range(80):
        px += 0.2
        bars.append({"ts": 1_700_000_000 + i * 60, "open": px, "high": px + 0.1, "low": px - 0.1, "close": px, "volume": 1})
    assert allow_after_losses(bars, 0) is True
    assert isinstance(allow_after_losses(bars, 2), bool)

def test_upper_third_close():
    assert close_in_upper_third({"high": 10, "low": 0, "close": 9})
    assert not close_in_upper_third({"high": 10, "low": 0, "close": 2})

def test_loss_sit_ignores_partial_15m_bucket():
    bars = []
    base = 1_700_000_100
    for i in range(45):
        px = 100 + i * 0.01
        bars.append({"ts": base + i * 60, "open": px, "high": px + 0.02, "low": px - 0.02, "close": px, "volume": 1})
    before = allow_after_losses(bars, 2)
    bars.append({"ts": base + 45 * 60, "open": 200, "high": 210, "low": 199, "close": 209, "volume": 1})
    assert before == allow_after_losses(bars, 2)
