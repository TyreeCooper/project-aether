from datetime import datetime, timedelta, timezone

from app.engine import BAR_HISTORY, PaperEngine, merge_bar_history


def test_daily_realized_resets_on_new_utc_day():
    engine = PaperEngine()
    engine.daily_realized = -50.0
    engine.daily_realized_date = (
        datetime.now(timezone.utc).date() - timedelta(days=1)
    ).isoformat()
    engine._roll_daily_if_needed(persist=False)
    assert engine.daily_realized == 0.0
    assert engine.daily_realized_date == datetime.now(timezone.utc).date().isoformat()


def test_restart_safe_default_is_offline():
    engine = PaperEngine()
    engine.state = "OFFLINE"
    assert engine.snapshot()["state"] == "OFFLINE"


def test_completed_bar_not_every_tick():
    engine = PaperEngine()
    engine._forming_bucket = None
    assert engine._update_forming_bar(100.0) is False
    before = len(engine.bars_1m)
    assert engine._update_forming_bar(100.1) is False
    assert len(engine.bars_1m) == before


def test_authoritative_closed_bar_replaces_sampled_candle():
    engine = PaperEngine()
    engine._forming_bucket = 1_700_000_000
    engine._forming_bar = {
        "ts": 1_700_000_000,
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 0.0,
    }
    authoritative = {
        "ts": 1_700_000_000,
        "open": 100.0,
        "high": 103.0,
        "low": 97.0,
        "close": 102.0,
        "volume": 12.0,
    }
    import app.engine as engine_mod
    old_now = engine_mod._now_dt
    try:
        engine_mod._now_dt = lambda: datetime.fromtimestamp(1_700_000_060, tz=timezone.utc)
        assert engine._update_forming_bar(102.5, authoritative_bar=authoritative) is True
    finally:
        engine_mod._now_dt = old_now
    assert engine.bars_1m[-1]["high"] == 103.0
    assert engine.bars_1m[-1]["low"] == 97.0
    assert engine.bars_1m[-1]["volume"] == 12.0


def test_merge_history_preserves_restored_bars_beyond_kraken_window():
    existing = [
        {
            "ts": 1_700_000_000 + i * 60,
            "open": 100 + i,
            "high": 101 + i,
            "low": 99 + i,
            "close": 100.5 + i,
            "volume": 1,
        }
        for i in range(900)
    ]
    incoming = [
        {
            "ts": 1_700_000_000 + i * 60,
            "open": 200 + i,
            "high": 201 + i,
            "low": 199 + i,
            "close": 200.5 + i,
            "volume": 2,
        }
        for i in range(500, 1220)
    ]
    merged = merge_bar_history(existing, incoming, BAR_HISTORY)
    assert len(merged) == 1220
    assert merged[0]["ts"] == existing[0]["ts"]
    assert merged[-1]["ts"] == incoming[-1]["ts"]
    overlap = next(row for row in merged if row["ts"] == incoming[0]["ts"])
    assert overlap["close"] == incoming[0]["close"]
    assert overlap["volume"] == 2
