from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aether_vnext.domain import (
    CalendarState,
    MarketObservation,
    QualityState,
    SessionState,
)
from aether_vnext.exit_plan import ExitReason
from aether_vnext.prototype_crypto_exit import evaluate_prototype_crypto_exit
from aether_vnext.prototype_history_sources import KRAKEN_DAILY_SOURCE_ID
from aether_vnext.prototype_market_history import PrototypeMarketBar


UTC = timezone.utc
OPENED = datetime(2026, 9, 30, 22, 15, tzinfo=UTC)
NOW = OPENED + timedelta(hours=2)


def _plan(*, deadline: datetime | None = None):
    return {
        "hard_stop_price": 95_000.0,
        "structure_rule_id": "frozen_breakout",
        "time_stop_deadline_utc": (
            None if deadline is None else deadline.isoformat()
        ),
        "trailing_policy": {
            "enabled": False,
            "start_condition": None,
            "ratchet_rule": None,
            "never_loosen": True,
        },
        "profit_take_policy": {"enabled": False, "rule_id": None},
        "session_close_policy": "hold",
        "stale_mark_policy": "hold",
        "governor_halt_behavior": "flatten",
    }


def _obs(
    *,
    bid: float = 100_000.0,
    ask: float = 100_020.0,
    quality: QualityState = QualityState.HEALTHY,
):
    mark = (bid + ask) / 2.0
    return MarketObservation(
        observation_id="obs-exit",
        asset_id="btc",
        venue="Kraken",
        bid=bid,
        ask=ask,
        last=mark,
        mark=mark,
        source="kraken_public",
        exchange_ts=NOW,
        received_ts=NOW,
        age_ms=0,
        spread_abs=ask - bid,
        spread_bps=((ask - bid) / mark) * 10_000.0,
        session_state=SessionState.ACTIVE,
        quality_state=quality,
        fallback_reason=None,
        calendar_state=CalendarState.ALWAYS_OPEN,
        data_version="test",
    )


def _bar(*, close: float = 100_500.0, closed_at: datetime | None = None):
    closed = closed_at or NOW
    return PrototypeMarketBar(
        asset_id="btc",
        interval_seconds=3600,
        bucket_open_utc=closed - timedelta(hours=1),
        bucket_close_utc=closed,
        open=100_400.0,
        high=max(100_600.0, close),
        low=min(100_300.0, close),
        close=close,
        volume=10.0,
        trade_count=100,
        source_id=KRAKEN_DAILY_SOURCE_ID,
        source_ref="kraken:test:completed-hour",
        available_at_utc=closed,
    )


def _evaluate(**overrides):
    args = {
        "asset_id": "btc",
        "side": "long",
        "opened_at_utc": OPENED,
        "exit_plan_payload": _plan(),
        "frozen_breakout_level": 99_000.0,
        "current_observation": _obs(),
        "latest_completed_hourly_bar": _bar(),
        "governor_halted": False,
        "as_of_utc": NOW,
    }
    args.update(overrides)
    return evaluate_prototype_crypto_exit(**args)


def test_governor_halt_has_first_precedence_even_through_hard_stop() -> None:
    out = _evaluate(
        governor_halted=True,
        current_observation=_obs(bid=94_000.0, ask=94_020.0),
        latest_completed_hourly_bar=_bar(close=98_000.0),
    )
    assert out.should_flatten is True
    assert out.exit_reason is ExitReason.GOVERNOR_HALT


def test_hard_stop_on_healthy_bid_precedes_structure() -> None:
    out = _evaluate(
        current_observation=_obs(bid=94_999.0, ask=95_010.0),
        latest_completed_hourly_bar=_bar(close=98_000.0),
    )
    assert out.exit_reason is ExitReason.HARD_STOP
    assert out.reason == "hard_stop_on_bid"


def test_structure_requires_future_completed_hour_close_strictly_below_breakout() -> None:
    below = _evaluate(latest_completed_hourly_bar=_bar(close=98_999.0))
    assert below.exit_reason is ExitReason.STRUCTURE

    equal = _evaluate(latest_completed_hourly_bar=_bar(close=99_000.0))
    assert equal.should_flatten is False

    signal_bar = _evaluate(
        latest_completed_hourly_bar=_bar(
            close=98_000.0,
            closed_at=OPENED - timedelta(minutes=15),
        )
    )
    assert signal_bar.should_flatten is False


def test_intrabar_bid_below_breakout_is_not_structure_invalidation() -> None:
    out = _evaluate(
        current_observation=_obs(bid=98_900.0, ask=98_920.0),
        latest_completed_hourly_bar=_bar(close=100_100.0),
    )
    assert out.should_flatten is False


def test_time_stop_follows_structure_and_is_five_day_plan_deadline() -> None:
    deadline = OPENED + timedelta(days=5)
    before = _evaluate(
        exit_plan_payload=_plan(deadline=deadline),
        as_of_utc=deadline - timedelta(seconds=1),
        latest_completed_hourly_bar=_bar(
            close=100_100.0,
            closed_at=OPENED + timedelta(days=4, hours=23),
        ),
    )
    assert before.should_flatten is False

    due_bar = _bar(
        close=100_100.0,
        closed_at=OPENED + timedelta(days=5),
    )
    due = _evaluate(
        exit_plan_payload=_plan(deadline=deadline),
        as_of_utc=deadline,
        latest_completed_hourly_bar=due_bar,
    )
    assert due.exit_reason is ExitReason.TIME_STOP


def test_stale_quote_does_not_manufacture_hard_stop() -> None:
    out = _evaluate(
        current_observation=_obs(
            bid=94_000.0,
            ask=94_020.0,
            quality=QualityState.STALE,
        ),
        latest_completed_hourly_bar=_bar(close=100_100.0),
    )
    assert out.should_flatten is False
