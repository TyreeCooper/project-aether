from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aether_vnext.domain import CalendarState, MarketObservation, QualityState, SessionState
from aether_vnext.market_truth import bar_is_closed, observation_is_valid
from aether_vnext.seed_truth import (
    ASSET_CALENDAR,
    ASSET_FEE_SCHEDULE,
    FEE_SCHEDULES,
    SEED_PRODUCT_MATH,
    SESSION_CALENDARS,
)


UTC = timezone.utc
NOW = datetime(2026, 9, 25, 20, 0, tzinfo=UTC)


def _obs(*, bid=99.0, ask=100.0, mark=99.5, age_ms=100, quality=QualityState.HEALTHY):
    return MarketObservation(
        observation_id="o1",
        asset_id="nvda",
        venue="paper",
        bid=bid,
        ask=ask,
        last=99.5,
        mark=mark,
        source="source",
        exchange_ts=NOW,
        received_ts=NOW,
        age_ms=age_ms,
        spread_abs=None if bid is None or ask is None else ask - bid,
        spread_bps=None,
        session_state=SessionState.ACTIVE,
        quality_state=quality,
        fallback_reason=None,
        calendar_state=CalendarState.NORMAL,
        data_version="v1",
    )


def test_seed_product_math_contains_all_twelve_assets() -> None:
    assert set(SEED_PRODUCT_MATH) == {
        "btc",
        "eth",
        "eurusd",
        "usdjpy",
        "mes",
        "mnq",
        "mgc",
        "mcl",
        "us10y",
        "nvda",
        "tsla",
        "pltr",
    }


def test_binding_seed_math_values_match_part_iii() -> None:
    assert SEED_PRODUCT_MATH["btc"].quantity_step == 0.0001
    assert SEED_PRODUCT_MATH["eth"].quantity_step == 0.001
    assert SEED_PRODUCT_MATH["eurusd"].quantity_step == 0.01
    assert SEED_PRODUCT_MATH["mes"].tick_size == 0.25
    assert SEED_PRODUCT_MATH["mes"].tick_value_usd == 1.25
    assert SEED_PRODUCT_MATH["mnq"].tick_value_usd == 0.50
    assert SEED_PRODUCT_MATH["mgc"].tick_size == 0.10
    assert SEED_PRODUCT_MATH["mcl"].tick_size == 0.01
    assert SEED_PRODUCT_MATH["us10y"].tick_size == 1 / 64
    assert SEED_PRODUCT_MATH["us10y"].tick_value_usd == 15.625
    assert SEED_PRODUCT_MATH["us10y"].executable_contract_family == "ZN"
    assert SEED_PRODUCT_MATH["nvda"].short_requires_locate is True


def test_fee_and_calendar_mappings_cover_seed_twelve() -> None:
    assert set(ASSET_FEE_SCHEDULE) == set(SEED_PRODUCT_MATH)
    assert set(ASSET_CALENDAR) == set(SEED_PRODUCT_MATH)
    assert set(FEE_SCHEDULES) == {
        "kraken_spot_taker_v1",
        "tastyfx_allin_v1",
        "ninja_micros_v1",
        "ibkr_equity_v1",
    }
    assert set(SESSION_CALENDARS) == {
        "crypto_24x7",
        "fx_otc",
        "us_rth",
        "us_fut_idx",
        "us_fut_metal_nrg",
        "us_fut_rates",
    }


def test_market_validity_rejects_stale_invalid_crossed_and_expired_quotes() -> None:
    assert observation_is_valid(_obs(), max_age_ms=500) is True
    assert observation_is_valid(_obs(age_ms=501), max_age_ms=500) is False
    assert observation_is_valid(
        _obs(quality=QualityState.STALE), max_age_ms=500
    ) is False
    assert observation_is_valid(
        _obs(quality=QualityState.INVALID), max_age_ms=500
    ) is False
    assert observation_is_valid(_obs(bid=101, ask=100), max_age_ms=500) is False


def test_bar_close_prefers_exchange_timestamp() -> None:
    opened = NOW
    interval = timedelta(minutes=15)
    assert bar_is_closed(
        bar_open_utc=opened,
        interval=interval,
        observation_exchange_ts=opened + interval,
        observation_received_ts=opened + timedelta(minutes=14, seconds=59),
    ) is True
    assert bar_is_closed(
        bar_open_utc=opened,
        interval=interval,
        observation_exchange_ts=opened + timedelta(minutes=14, seconds=59),
        observation_received_ts=opened + interval + timedelta(seconds=10),
    ) is False


def test_bar_close_uses_two_second_received_grace_without_exchange_ts() -> None:
    opened = NOW
    interval = timedelta(minutes=15)
    assert bar_is_closed(
        bar_open_utc=opened,
        interval=interval,
        observation_exchange_ts=None,
        observation_received_ts=opened + interval + timedelta(seconds=1),
    ) is False
    assert bar_is_closed(
        bar_open_utc=opened,
        interval=interval,
        observation_exchange_ts=None,
        observation_received_ts=opened + interval + timedelta(seconds=2),
    ) is True


def test_session_close_can_end_last_bar_early() -> None:
    opened = NOW
    interval = timedelta(hours=1)
    session_close = NOW + timedelta(minutes=30)
    assert bar_is_closed(
        bar_open_utc=opened,
        interval=interval,
        observation_exchange_ts=session_close,
        observation_received_ts=session_close,
        session_close_utc=session_close,
    ) is True
