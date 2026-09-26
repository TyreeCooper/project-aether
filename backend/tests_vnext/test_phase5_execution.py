from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.domain import (
    CalendarState,
    Lineage,
    MarketObservation,
    OrderIntent,
    OrderIntentState,
    QualityState,
    SessionState,
)
from aether_vnext.execution import (
    PAPER_ACK_MS,
    PAPER_SUBMIT_TIMEOUT_MS,
    PaperExecutionPolicy,
    cancel_stale_paper_intent,
    entry_fill_price,
    fill_submitted_paper_intent,
    paper_fill_due_at,
    stop_exit_fill_price,
    stop_triggered,
    submit_paper_intent,
)
from aether_vnext.registry import SEED_REGISTRY


UTC = timezone.utc
T0 = datetime(2026, 9, 26, 5, 30, tzinfo=UTC)


def _lineage() -> Lineage:
    return Lineage(
        asset_id="btc",
        route_id="btc:daily_swing:long",
        policy_version="policy-v1",
        configuration_hash="cfg",
        market_observation_id="obs-ready",
        created_at_utc=T0,
        ticket_id="ticket-1",
    )


def _intent(
    *,
    state: OrderIntentState = OrderIntentState.RESERVED,
    side: str = "long",
    submitted_at: datetime | None = None,
    acknowledged_at: datetime | None = None,
) -> OrderIntent:
    return OrderIntent(
        order_intent_id="intent-1",
        lineage=_lineage(),
        broker="Kraken",
        venue="Kraken",
        symbol="XBTUSD",
        side=side,
        qty=0.01,
        order_type="market",
        reference_price=100_000.0,
        expected_fill=None,
        state=state,
        submitted_at=submitted_at,
        acknowledged_at=acknowledged_at,
        filled_at=None,
        filled_qty=0.0,
        avg_fill_price=None,
        reject_code=None,
        slippage_usd=None,
        slippage_bps=None,
        idempotency_key="idem-1",
    )


def _obs(
    *,
    bid: float = 99_990.0,
    ask: float = 100_010.0,
    age_ms: int = 10,
    spread_bps: float = 2.0,
    quality: QualityState = QualityState.HEALTHY,
    session: SessionState = SessionState.ACTIVE,
) -> MarketObservation:
    return MarketObservation(
        observation_id="obs-fill",
        asset_id="btc",
        venue="Kraken",
        bid=bid,
        ask=ask,
        last=100_000.0,
        mark=(bid + ask) / 2.0,
        source="kraken_public",
        exchange_ts=T0,
        received_ts=T0,
        age_ms=age_ms,
        spread_abs=ask - bid,
        spread_bps=spread_bps,
        session_state=session,
        quality_state=quality,
        fallback_reason=None,
        calendar_state=CalendarState.ALWAYS_OPEN,
        data_version="v1",
    )


def test_submit_is_two_phase_not_instant_open() -> None:
    transition = submit_paper_intent(_intent(), at_utc=T0)
    assert transition.applied is True
    assert transition.intent.state is OrderIntentState.SUBMITTED
    assert transition.intent.submitted_at == T0
    assert transition.intent.acknowledged_at == T0
    assert transition.intent.filled_qty == 0.0


def test_paper_fill_latency_is_exactly_250ms_default() -> None:
    submitted = submit_paper_intent(_intent(), at_utc=T0).intent
    assert PAPER_ACK_MS == 250
    assert paper_fill_due_at(submitted) == T0 + timedelta(milliseconds=250)

    early = fill_submitted_paper_intent(
        submitted,
        observation=_obs(),
        registry_row=SEED_REGISTRY["btc"],
        ready_spread_bps=2.0,
        hard_stop_price=95_000.0,
        max_age_ms=1_000,
        at_utc=T0 + timedelta(milliseconds=249),
    )
    assert early.applied is False
    assert early.reason == "paper_latency_wait"


def test_long_entry_fills_from_ask_plus_5bps_and_all_or_none() -> None:
    submitted = submit_paper_intent(_intent(), at_utc=T0).intent
    obs = _obs()
    transition = fill_submitted_paper_intent(
        submitted,
        observation=obs,
        registry_row=SEED_REGISTRY["btc"],
        ready_spread_bps=2.0,
        hard_stop_price=95_000.0,
        max_age_ms=1_000,
        at_utc=T0 + timedelta(milliseconds=250),
    )
    assert transition.applied is True
    assert transition.intent.state is OrderIntentState.FILLED
    assert transition.intent.filled_qty == submitted.qty
    assert transition.intent.avg_fill_price == pytest.approx(
        obs.ask * 1.0005
    )
    assert transition.intent.slippage_bps == 5.0
    assert transition.intent.slippage_usd is not None
    assert transition.intent.slippage_usd > 0


def test_short_entry_fills_from_bid_minus_5bps() -> None:
    intent = _intent(side="short")
    submitted = submit_paper_intent(intent, at_utc=T0).intent
    obs = _obs()
    transition = fill_submitted_paper_intent(
        submitted,
        observation=obs,
        registry_row=SEED_REGISTRY["btc"],
        ready_spread_bps=2.0,
        hard_stop_price=105_000.0,
        max_age_ms=1_000,
        at_utc=T0 + timedelta(milliseconds=250),
    )
    assert transition.intent.state is OrderIntentState.FILLED
    assert transition.intent.avg_fill_price == pytest.approx(
        obs.bid * 0.9995
    )


def test_stale_invalid_or_closed_market_rejects_before_fill() -> None:
    submitted = submit_paper_intent(_intent(), at_utc=T0).intent
    for obs, expected in (
        (_obs(quality=QualityState.STALE), "market_stale"),
        (_obs(quality=QualityState.INVALID), "market_stale"),
        (_obs(session=SessionState.CLOSED), "market_changed"),
    ):
        transition = fill_submitted_paper_intent(
            submitted,
            observation=obs,
            registry_row=SEED_REGISTRY["btc"],
            ready_spread_bps=2.0,
            hard_stop_price=95_000.0,
            max_age_ms=1_000,
            at_utc=T0 + timedelta(milliseconds=250),
        )
        assert transition.intent.state is OrderIntentState.REJECTED
        assert transition.intent.reject_code == expected


def test_spread_more_than_twice_ready_rejects_market_changed() -> None:
    submitted = submit_paper_intent(_intent(), at_utc=T0).intent
    transition = fill_submitted_paper_intent(
        submitted,
        observation=_obs(spread_bps=4.01),
        registry_row=SEED_REGISTRY["btc"],
        ready_spread_bps=2.0,
        hard_stop_price=95_000.0,
        max_age_ms=1_000,
        at_utc=T0 + timedelta(milliseconds=250),
    )
    assert transition.intent.state is OrderIntentState.REJECTED
    assert transition.intent.reject_code == "market_changed"


def test_stop_already_through_before_entry_rejects_market_changed() -> None:
    submitted = submit_paper_intent(_intent(), at_utc=T0).intent
    obs = _obs(bid=94_900.0, ask=94_920.0)
    transition = fill_submitted_paper_intent(
        submitted,
        observation=obs,
        registry_row=SEED_REGISTRY["btc"],
        ready_spread_bps=3.0,
        hard_stop_price=95_000.0,
        max_age_ms=1_000,
        at_utc=T0 + timedelta(milliseconds=250),
    )
    assert stop_triggered(
        obs,
        position_side="long",
        hard_stop_price=95_000.0,
    ) is True
    assert transition.intent.state is OrderIntentState.REJECTED
    assert transition.intent.reject_code == "market_changed"


def test_gap_through_stop_exit_uses_first_conservative_through_price() -> None:
    long_obs = _obs(bid=90_000.0, ask=90_020.0)
    assert stop_exit_fill_price(
        long_obs,
        position_side="long",
        hard_stop_price=95_000.0,
    ) == pytest.approx(90_000.0 * 0.9995)

    short_obs = _obs(bid=109_980.0, ask=110_000.0)
    assert stop_exit_fill_price(
        short_obs,
        position_side="short",
        hard_stop_price=105_000.0,
    ) == pytest.approx(110_000.0 * 1.0005)


def test_stale_submit_timeout_is_15_seconds_and_terminal_wins() -> None:
    assert PAPER_SUBMIT_TIMEOUT_MS == 15_000
    submitted = submit_paper_intent(_intent(), at_utc=T0).intent

    not_yet = cancel_stale_paper_intent(
        submitted,
        at_utc=T0 + timedelta(seconds=15),
    )
    assert not_yet.applied is False
    assert not_yet.reason == "not_stale"

    stale = cancel_stale_paper_intent(
        submitted,
        at_utc=T0 + timedelta(seconds=15, milliseconds=1),
    )
    assert stale.applied is True
    assert stale.intent.state is OrderIntentState.CANCELLED_STALE

    late_fill = fill_submitted_paper_intent(
        stale.intent,
        observation=_obs(),
        registry_row=SEED_REGISTRY["btc"],
        ready_spread_bps=2.0,
        hard_stop_price=95_000.0,
        max_age_ms=1_000,
        at_utc=T0 + timedelta(seconds=16),
    )
    assert late_fill.applied is False
    assert late_fill.reason == "terminal_state_wins"
    assert late_fill.intent.state is OrderIntentState.CANCELLED_STALE


def test_seed_twelve_paper_does_not_invent_partials() -> None:
    submitted = submit_paper_intent(_intent(), at_utc=T0).intent
    transition = fill_submitted_paper_intent(
        submitted,
        observation=_obs(),
        registry_row=SEED_REGISTRY["btc"],
        ready_spread_bps=2.0,
        hard_stop_price=95_000.0,
        max_age_ms=1_000,
        at_utc=T0 + timedelta(milliseconds=250),
        policy=PaperExecutionPolicy(partials_enabled=True),
    )
    assert transition.applied is False
    assert transition.reason == "partial_policy_not_implemented"


def test_entry_fill_never_uses_mid_or_last() -> None:
    obs = _obs(bid=99.0, ask=101.0)
    assert entry_fill_price(obs, position_side="long") == pytest.approx(
        101.0 * 1.0005
    )
    assert entry_fill_price(obs, position_side="short") == pytest.approx(
        99.0 * 0.9995
    )
