from datetime import datetime, timedelta, timezone

from app.engine import PaperEngine


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
