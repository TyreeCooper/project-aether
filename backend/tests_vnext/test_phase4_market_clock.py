from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.adapters import KrakenPublicTickerV2
from aether_vnext.bars import ClosedBarBuilder, MarketPrint
from aether_vnext.calendars import CalendarDecision
from aether_vnext.domain import CalendarState, QualityState, SessionState
from aether_vnext.market_data import RawQuote, normalize_quote, select_source
from aether_vnext.market_truth import observation_is_valid
from aether_vnext.registry import SEED_REGISTRY, bind_market_data
from aether_vnext.trading_clock import RouteClockSpec, TradingClock


UTC = timezone.utc
T0 = datetime(2026, 9, 26, 5, 0, 0, tzinfo=UTC)


def _calendar(*, eligible: bool = True) -> CalendarDecision:
    return CalendarDecision(
        calendar_id="crypto_24x7",
        session_state=(
            SessionState.ACTIVE if eligible else SessionState.CLOSED
        ),
        calendar_state=CalendarState.ALWAYS_OPEN,
        eligible=eligible,
        focus=eligible,
        reason="24x7" if eligible else "closed",
    )


def _quote(
    *,
    asset_id: str = "btc",
    source_id: str = "primary",
    exchange_ts: datetime | None = T0,
    received_ts: datetime = T0,
    bid: float = 99.0,
    ask: float = 101.0,
    last: float = 100.0,
    mark: float = 100.0,
) -> RawQuote:
    return RawQuote(
        asset_id=asset_id,
        venue="Kraken",
        source_id=source_id,
        bid=bid,
        ask=ask,
        last=last,
        mark=mark,
        exchange_ts=exchange_ts,
        received_ts=received_ts,
        adapter_version="test:v1",
    )


def test_kraken_parser_emits_only_supported_quote_contracts() -> None:
    parser = KrakenPublicTickerV2()
    payload = {
        "channel": "ticker",
        "data": [
            {
                "symbol": "BTC/USD",
                "last": 100000,
                "bid": 99990,
                "ask": 100010,
                "timestamp": "2026-09-26T05:00:00Z",
            },
            {
                "symbol": "ETH/USD",
                "last": 4000,
                "bid": 3999,
                "ask": 4001,
                "timestamp": "2026-09-26T05:00:00Z",
            },
            {
                "symbol": "DOGE/USD",
                "last": 1,
                "bid": 0.99,
                "ask": 1.01,
            },
        ],
    }
    rows = parser.parse_quote(payload, received_at_utc=T0)
    assert [row.asset_id for row in rows] == ["btc", "eth"]
    assert rows[0].source_id == "kraken_public"
    assert rows[0].mark == pytest.approx(100000.0)
    assert rows[0].exchange_ts == T0


def test_source_selection_filters_same_provider_payload_by_asset() -> None:
    row = bind_market_data(
        SEED_REGISTRY["btc"],
        primary_source_id="primary",
        fallback_source_id="fallback",
        stale_threshold_ms=1_000,
    )
    selection = select_source(
        (
            _quote(asset_id="eth", source_id="primary"),
            _quote(asset_id="btc", source_id="primary"),
        ),
        registry_row=row,
        calendar=_calendar(),
        as_of_utc=T0,
        stale_threshold_ms=1_000,
    )
    assert selection.observation is not None
    assert selection.observation.asset_id == "btc"
    assert selection.observation.source == "primary"


def test_stale_primary_fails_over_to_healthy_fallback() -> None:
    row = bind_market_data(
        SEED_REGISTRY["btc"],
        primary_source_id="primary",
        fallback_source_id="fallback",
        stale_threshold_ms=1_000,
    )
    stale = _quote(
        source_id="primary",
        exchange_ts=T0 - timedelta(seconds=5),
        received_ts=T0 - timedelta(seconds=5),
    )
    fallback = _quote(source_id="fallback")
    selection = select_source(
        (stale, fallback),
        registry_row=row,
        calendar=_calendar(),
        as_of_utc=T0,
        stale_threshold_ms=1_000,
    )
    assert selection.observation is not None
    assert selection.observation.source == "fallback"
    assert selection.observation.quality_state is QualityState.DEGRADED
    assert selection.observation.fallback_reason == "primary_unusable:primary"
    assert "primary:stale" in selection.rejection_reasons


def test_future_market_timestamp_is_rejected_not_clamped_to_fresh() -> None:
    row = bind_market_data(
        SEED_REGISTRY["btc"],
        primary_source_id="primary",
        stale_threshold_ms=1_000,
    )
    future = _quote(
        source_id="primary",
        exchange_ts=T0 + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="after decision time"):
        normalize_quote(
            future,
            registry_row=row,
            calendar=_calendar(),
            as_of_utc=T0,
            stale_threshold_ms=1_000,
        )


def test_calendar_ineligible_observation_cannot_pass_market_validity() -> None:
    row = bind_market_data(
        SEED_REGISTRY["btc"],
        primary_source_id="primary",
        stale_threshold_ms=1_000,
    )
    obs = normalize_quote(
        _quote(source_id="primary"),
        registry_row=row,
        calendar=_calendar(eligible=False),
        as_of_utc=T0,
        stale_threshold_ms=1_000,
    )
    assert obs.quality_state is QualityState.HEALTHY
    assert obs.session_state is SessionState.CLOSED
    assert observation_is_valid(obs, max_age_ms=1_000) is False


def test_crossed_book_is_invalid_and_never_selected() -> None:
    row = bind_market_data(
        SEED_REGISTRY["btc"],
        primary_source_id="primary",
        stale_threshold_ms=1_000,
    )
    selection = select_source(
        (_quote(source_id="primary", bid=101.0, ask=100.0),),
        registry_row=row,
        calendar=_calendar(),
        as_of_utc=T0,
        stale_threshold_ms=1_000,
    )
    assert selection.observation is None
    assert "primary:invalid" in selection.rejection_reasons


def test_bar_builder_closes_populated_bucket_without_synthesizing_gaps() -> None:
    builder = ClosedBarBuilder(
        asset_id="btc",
        interval=timedelta(minutes=1),
        venue_timezone="UTC",
    )
    assert builder.push(
        MarketPrint(
            asset_id="btc",
            price=100.0,
            volume=1.0,
            exchange_ts=T0 + timedelta(seconds=10),
            received_ts=T0 + timedelta(seconds=10),
            source_id="kraken_public",
        )
    ) == ()

    closed = builder.push(
        MarketPrint(
            asset_id="btc",
            price=103.0,
            volume=2.0,
            exchange_ts=T0 + timedelta(minutes=3, seconds=1),
            received_ts=T0 + timedelta(minutes=3, seconds=1),
            source_id="kraken_public",
        )
    )
    assert len(closed) == 1
    assert closed[0].bucket_open_utc == T0
    assert closed[0].bucket_close_utc == T0 + timedelta(minutes=1)
    assert builder.forming_bar is not None
    assert builder.forming_bar.bucket_open_utc == T0 + timedelta(minutes=3)


def test_bar_builder_rejects_out_of_order_exchange_time() -> None:
    builder = ClosedBarBuilder(
        asset_id="btc",
        interval=timedelta(minutes=1),
        venue_timezone="UTC",
    )
    builder.push(
        MarketPrint(
            asset_id="btc",
            price=101.0,
            volume=1.0,
            exchange_ts=T0 + timedelta(minutes=2),
            received_ts=T0 + timedelta(minutes=2),
            source_id="kraken_public",
        )
    )
    with pytest.raises(ValueError, match="out-of-order"):
        builder.push(
            MarketPrint(
                asset_id="btc",
                price=100.0,
                volume=1.0,
                exchange_ts=T0 + timedelta(minutes=1),
                received_ts=T0 + timedelta(minutes=2, seconds=1),
                source_id="kraken_public",
            )
        )


def test_trading_clock_requires_completed_matching_trigger_bar_once() -> None:
    builder = ClosedBarBuilder(
        asset_id="btc",
        interval=timedelta(minutes=1),
        venue_timezone="UTC",
    )
    builder.push(
        MarketPrint(
            asset_id="btc",
            price=100.0,
            volume=1.0,
            exchange_ts=T0 + timedelta(seconds=5),
            received_ts=T0 + timedelta(seconds=5),
            source_id="kraken_public",
        )
    )
    closed = builder.push(
        MarketPrint(
            asset_id="btc",
            price=101.0,
            volume=1.0,
            exchange_ts=T0 + timedelta(minutes=1),
            received_ts=T0 + timedelta(minutes=1),
            source_id="kraken_public",
        )
    )[0]

    spec = RouteClockSpec(
        route_key="btc:test:long",
        asset_id="btc",
        horizon="test",
        trigger_interval=timedelta(minutes=1),
    )
    clock = TradingClock()

    due = clock.inspect(
        spec=spec,
        closed_bar=closed,
        calendar=_calendar(),
        as_of_utc=T0 + timedelta(minutes=1),
    )
    assert due.due is True
    assert due.reason == "clock_due"
    clock.consume(due)

    duplicate = clock.inspect(
        spec=spec,
        closed_bar=closed,
        calendar=_calendar(),
        as_of_utc=T0 + timedelta(minutes=2),
    )
    assert duplicate.due is False
    assert duplicate.reason == "clock_already_consumed"


def test_trading_clock_never_fires_from_forming_or_wrong_interval_bar() -> None:
    builder = ClosedBarBuilder(
        asset_id="btc",
        interval=timedelta(minutes=1),
        venue_timezone="UTC",
    )
    builder.push(
        MarketPrint(
            asset_id="btc",
            price=100.0,
            volume=1.0,
            exchange_ts=T0 + timedelta(seconds=10),
            received_ts=T0 + timedelta(seconds=10),
            source_id="kraken_public",
        )
    )
    spec = RouteClockSpec(
        route_key="btc:test:long",
        asset_id="btc",
        horizon="test",
        trigger_interval=timedelta(minutes=15),
    )
    clock = TradingClock()

    no_closed_bar = clock.inspect(
        spec=spec,
        closed_bar=None,
        calendar=_calendar(),
        as_of_utc=T0 + timedelta(seconds=30),
    )
    assert no_closed_bar.due is False
    assert no_closed_bar.reason == "forming_bar"

    one_minute_closed = builder.close_at_session_end(
        session_close_utc=T0 + timedelta(minutes=1),
        received_ts=T0 + timedelta(minutes=1),
    )[0]
    wrong_interval = clock.inspect(
        spec=spec,
        closed_bar=one_minute_closed,
        calendar=_calendar(),
        as_of_utc=T0 + timedelta(minutes=1),
    )
    assert wrong_interval.due is False
    assert wrong_interval.reason == "wrong_trigger_interval"


def test_trading_clock_route_gates_are_before_strategy_evaluation() -> None:
    clock = TradingClock()
    unsupported = RouteClockSpec(
        route_key="btc:test:long",
        asset_id="btc",
        horizon="test",
        trigger_interval=timedelta(minutes=1),
        supported=False,
    )
    decision = clock.inspect(
        spec=unsupported,
        closed_bar=None,
        calendar=_calendar(),
        as_of_utc=T0,
    )
    assert decision.due is False
    assert decision.reason == "route_unsupported"
