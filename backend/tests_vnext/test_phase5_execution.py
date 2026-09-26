from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

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
    exit_fill_price,
    fill_submitted_paper_intent,
    paper_fill_due_at,
    stop_exit_fill_price,
    stop_triggered,
    submit_paper_intent,
)
from aether_vnext.reconciler import (
    RECONCILER_INTERVAL_SECONDS,
    reconcile_stale_intents,
)
from aether_vnext.registry import SEED_REGISTRY
from aether_vnext.store import VNextStore


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


def _store_fixture():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        assert store.provision_seed_ledgers_once(conn) is True
    return engine, store


def _reserve_btc(
    conn,
    store: VNextStore,
    *,
    order_intent_id: str = "intent-reserve-1",
    idempotency_key: str = "idem-reserve-1",
    reserve_cash_usd: float = 100.0,
    reserve_margin_usd: float = 0.0,
):
    return store.reserve_order_intent(
        conn,
        order_intent_id=order_intent_id,
        ticket_id="ticket-1",
        firm_event_id=None,
        asset_id="btc",
        route_id="btc:daily_swing:long",
        broker_account_id="kraken_paper",
        broker="Kraken",
        venue="Kraken",
        symbol="XBTUSD",
        side="long",
        qty=0.01,
        order_type="market",
        reference_price=100_000.0,
        expected_fill=100_060.0,
        idempotency_key=idempotency_key,
        signal_key="signal-1",
        position_key="btc:daily_swing",
        reserve_cash_usd=reserve_cash_usd,
        reserve_margin_usd=reserve_margin_usd,
        ready_spread_bps=2.0,
        hard_stop_price=95_000.0,
        exit_plan_id=None,
        submit_timeout_at=None,
        policy_version="policy-v1",
        configuration_hash="cfg",
        market_observation_id="obs-ready",
        created_at_utc=T0,
        event_id=f"evt-{order_intent_id}",
        actor="test",
    )


def test_phase_a_reserve_moves_only_target_broker_ledger_and_not_signal() -> None:
    engine, store = _store_fixture()
    with engine.begin() as conn:
        out = _reserve_btc(conn, store)
        assert out["ok"] is True
        assert out["state"] == "RESERVED"

        rows = {
            row["broker_account_id"]: row
            for row in store.ledger_rows(conn)
        }
        assert rows["kraken_paper"]["cash_available_usd"] == pytest.approx(3900.0)
        assert rows["kraken_paper"]["cash_reserved_usd"] == pytest.approx(100.0)
        assert rows["tastyfx_paper"]["cash_available_usd"] == pytest.approx(2000.0)
        assert rows["ninja_paper"]["cash_available_usd"] == pytest.approx(2000.0)
        assert rows["ibkr_paper"]["cash_available_usd"] == pytest.approx(2000.0)

        consumed = conn.execute(
            sa.select(sa.func.count()).select_from(store.tables["signal_consumptions"])
        ).scalar_one()
        assert consumed == 0


def test_phase_a_duplicate_idempotency_does_not_double_reserve() -> None:
    engine, store = _store_fixture()
    with engine.begin() as conn:
        first = _reserve_btc(conn, store)
        second = _reserve_btc(
            conn,
            store,
            order_intent_id="intent-different",
            idempotency_key="idem-reserve-1",
        )
        assert first["duplicate"] is False
        assert second["duplicate"] is True
        ledger = {
            row["broker_account_id"]: row
            for row in store.ledger_rows(conn)
        }["kraken_paper"]
        assert ledger["cash_available_usd"] == pytest.approx(3900.0)
        assert ledger["cash_reserved_usd"] == pytest.approx(100.0)


def test_phase_a_insufficient_broker_cash_rolls_back_reservation_shape() -> None:
    engine, store = _store_fixture()
    with engine.begin() as conn:
        out = _reserve_btc(
            conn,
            store,
            order_intent_id="intent-too-big",
            idempotency_key="idem-too-big",
            reserve_cash_usd=5000.0,
        )
        assert out["ok"] is False
        assert out["error"] == "insufficient_capital"
        ledger = {
            row["broker_account_id"]: row
            for row in store.ledger_rows(conn)
        }["kraken_paper"]
        assert ledger["cash_available_usd"] == pytest.approx(4000.0)
        assert ledger["cash_reserved_usd"] == 0.0
        intents = conn.execute(
            sa.select(sa.func.count()).select_from(store.tables["order_intents"])
        ).scalar_one()
        assert intents == 0


def test_submit_and_reject_release_are_separate_transactions_and_idempotent() -> None:
    engine, store = _store_fixture()
    with engine.begin() as conn:
        _reserve_btc(conn, store)

    with engine.begin() as conn:
        submitted = store.mark_order_intent_submitted(
            conn,
            order_intent_id="intent-reserve-1",
            submitted_at_utc=T0,
            acknowledged_at_utc=T0,
            submit_timeout_at=T0 + timedelta(seconds=15),
            event_id="evt-submit-1",
            actor="paper-adapter",
        )
        assert submitted["state"] == "SUBMITTED"

    with engine.begin() as conn:
        duplicate_submit = store.mark_order_intent_submitted(
            conn,
            order_intent_id="intent-reserve-1",
            submitted_at_utc=T0,
            acknowledged_at_utc=T0,
            submit_timeout_at=T0 + timedelta(seconds=15),
            event_id="evt-submit-duplicate",
            actor="paper-adapter",
        )
        assert duplicate_submit["duplicate"] is True

    with engine.begin() as conn:
        released = store.release_order_reservation(
            conn,
            order_intent_id="intent-reserve-1",
            terminal_state="REJECTED",
            reject_code="market_stale",
            at_utc=T0 + timedelta(milliseconds=250),
            event_id="evt-reject-1",
            actor="paper-adapter",
            fill_market_observation_id=None,
        )
        assert released["state"] == "REJECTED"

    with engine.begin() as conn:
        duplicate_release = store.release_order_reservation(
            conn,
            order_intent_id="intent-reserve-1",
            terminal_state="REJECTED",
            reject_code="market_stale",
            at_utc=T0 + timedelta(milliseconds=251),
            event_id="evt-reject-duplicate",
            actor="paper-adapter",
            fill_market_observation_id=None,
        )
        assert duplicate_release["duplicate"] is True
        ledger = {
            row["broker_account_id"]: row
            for row in store.ledger_rows(conn)
        }["kraken_paper"]
        assert ledger["cash_available_usd"] == pytest.approx(4000.0)
        assert ledger["cash_reserved_usd"] == 0.0


def test_margin_reservation_and_release_use_same_broker_ledger() -> None:
    engine, store = _store_fixture()
    with engine.begin() as conn:
        out = store.reserve_order_intent(
            conn,
            order_intent_id="intent-mes-1",
            ticket_id="ticket-mes",
            firm_event_id=None,
            asset_id="mes",
            route_id="mes:intraday:long",
            broker_account_id="ninja_paper",
            broker="NinjaTrader",
            venue="NinjaTrader",
            symbol="MESZ26",
            side="long",
            qty=1.0,
            order_type="market",
            reference_price=6000.0,
            expected_fill=6003.0,
            idempotency_key="idem-mes-1",
            signal_key="signal-mes-1",
            position_key="mes:intraday",
            reserve_cash_usd=0.0,
            reserve_margin_usd=1200.0,
            ready_spread_bps=1.0,
            hard_stop_price=5900.0,
            exit_plan_id=None,
            submit_timeout_at=None,
            policy_version="policy-v1",
            configuration_hash="cfg",
            market_observation_id="obs-ready-mes",
            created_at_utc=T0,
            event_id="evt-mes-reserve",
            actor="test",
        )
        assert out["ok"] is True
        ledger = {
            row["broker_account_id"]: row
            for row in store.ledger_rows(conn)
        }["ninja_paper"]
        assert ledger["margin_used_usd"] == pytest.approx(1200.0)
        assert ledger["margin_available_usd"] == pytest.approx(800.0)

    with engine.begin() as conn:
        store.release_order_reservation(
            conn,
            order_intent_id="intent-mes-1",
            terminal_state="CANCELLED_STALE",
            reject_code="submit_timeout",
            at_utc=T0 + timedelta(seconds=16),
            event_id="evt-mes-release",
            actor="reconciler",
        )
        ledger = {
            row["broker_account_id"]: row
            for row in store.ledger_rows(conn)
        }["ninja_paper"]
        assert ledger["margin_used_usd"] == 0.0
        assert ledger["margin_available_usd"] == pytest.approx(2000.0)


def _submit_reserved_btc(conn, store: VNextStore) -> None:
    out = _reserve_btc(conn, store)
    assert out["ok"] is True
    submitted = store.mark_order_intent_submitted(
        conn,
        order_intent_id="intent-reserve-1",
        submitted_at_utc=T0,
        acknowledged_at_utc=T0,
        submit_timeout_at=None,
        event_id="evt-submit-btc",
        actor="paper-adapter",
    )
    assert submitted["state"] == "SUBMITTED"


def _finalize_btc(conn, store: VNextStore, *, trade_id: str = "trade-1", qty: float = 0.01):
    return store.finalize_filled_open(
        conn,
        order_intent_id="intent-reserve-1",
        trade_id=trade_id,
        setup_id="setup-1",
        exit_plan_id="exit-plan-1",
        fill_market_observation_id="obs-fill",
        filled_at_utc=T0 + timedelta(milliseconds=250),
        filled_qty=qty,
        avg_fill_price=100_060.005,
        slippage_usd=0.5,
        slippage_bps=5.0,
        initial_stop_risk_usd=50.0,
        exit_plan_version="v1",
        exit_plan_payload={"hard_stop_price": 95_000.0},
        management_telemetry={},
        event_id=f"evt-fill-{trade_id}",
        actor="paper-adapter",
    )


def test_successful_fill_atomically_opens_consumes_signal_and_retains_reserve() -> None:
    engine, store = _store_fixture()
    with engine.begin() as conn:
        _submit_reserved_btc(conn, store)

    with engine.begin() as conn:
        result = _finalize_btc(conn, store)
        assert result["ok"] is True
        assert result["state"] == "FILLED"

        intents = store.tables["order_intents"]
        intent = conn.execute(
            sa.select(intents).where(
                intents.c.order_intent_id == "intent-reserve-1"
            )
        ).mappings().one()
        assert intent["state"] == "FILLED"
        assert intent["trade_id"] == "trade-1"
        assert intent["filled_qty"] == pytest.approx(0.01)
        assert intent["fill_market_observation_id"] == "obs-fill"

        open_trades = conn.execute(
            sa.select(store.tables["open_trades"])
        ).mappings().all()
        assert len(open_trades) == 1
        assert open_trades[0]["trade_id"] == "trade-1"
        assert open_trades[0]["exit_plan_id"] == "exit-plan-1"

        active = conn.execute(
            sa.select(store.tables["active_positions"])
        ).mappings().one()
        assert active["position_key"] == "btc:daily_swing"
        assert active["trade_id"] == "trade-1"

        consumed = conn.execute(
            sa.select(store.tables["signal_consumptions"])
        ).mappings().one()
        assert consumed["signal_key"] == "signal-1"
        assert consumed["trade_id"] == "trade-1"

        ledger = {
            row["broker_account_id"]: row
            for row in store.ledger_rows(conn)
        }["kraken_paper"]
        # v4.2.1: reservation remains locked while OPEN; it is released on FLAT.
        assert ledger["cash_available_usd"] == pytest.approx(3900.0)
        assert ledger["cash_reserved_usd"] == pytest.approx(100.0)


def test_duplicate_fill_event_is_noop_and_does_not_duplicate_exposure() -> None:
    engine, store = _store_fixture()
    with engine.begin() as conn:
        _submit_reserved_btc(conn, store)
        first = _finalize_btc(conn, store)
        second = _finalize_btc(
            conn,
            store,
            trade_id="trade-should-not-exist",
        )
        assert first["duplicate"] is False
        assert second["duplicate"] is True
        assert second["trade_id"] == "trade-1"

        assert conn.execute(
            sa.select(sa.func.count()).select_from(store.tables["open_trades"])
        ).scalar_one() == 1
        assert conn.execute(
            sa.select(sa.func.count()).select_from(store.tables["active_positions"])
        ).scalar_one() == 1
        assert conn.execute(
            sa.select(sa.func.count()).select_from(store.tables["signal_consumptions"])
        ).scalar_one() == 1


def test_partial_fill_is_refused_without_consuming_signal_or_opening() -> None:
    engine, store = _store_fixture()
    with engine.begin() as conn:
        _submit_reserved_btc(conn, store)
        result = _finalize_btc(conn, store, qty=0.005)
        assert result["ok"] is False
        assert result["error"] == "partial_fill_disabled"
        assert conn.execute(
            sa.select(sa.func.count()).select_from(store.tables["open_trades"])
        ).scalar_one() == 0
        assert conn.execute(
            sa.select(sa.func.count()).select_from(store.tables["signal_consumptions"])
        ).scalar_one() == 0

        ledger = {
            row["broker_account_id"]: row
            for row in store.ledger_rows(conn)
        }["kraken_paper"]
        assert ledger["cash_reserved_usd"] == pytest.approx(100.0)


def test_reservation_timeout_is_durable_from_phase_a_not_submit_time() -> None:
    engine, store = _store_fixture()
    with engine.begin() as conn:
        _reserve_btc(conn, store)
        intents = store.tables["order_intents"]
        row = conn.execute(
            sa.select(intents).where(
                intents.c.order_intent_id == "intent-reserve-1"
            )
        ).mappings().one()
        # SQLite drops tzinfo on DateTime round-trip; PostgreSQL preserves it.
        assert row["submit_timeout_at"].replace(tzinfo=UTC) == (
            T0 + timedelta(seconds=15)
        )

    with engine.begin() as conn:
        # Submit later; timeout remains anchored to reservation time.
        store.mark_order_intent_submitted(
            conn,
            order_intent_id="intent-reserve-1",
            submitted_at_utc=T0 + timedelta(seconds=5),
            acknowledged_at_utc=T0 + timedelta(seconds=5),
            submit_timeout_at=T0 + timedelta(seconds=20),
            event_id="evt-late-submit",
            actor="paper-adapter",
        )
        row = conn.execute(
            sa.select(store.tables["order_intents"]).where(
                store.tables["order_intents"].c.order_intent_id
                == "intent-reserve-1"
            )
        ).mappings().one()
        assert row["submit_timeout_at"].replace(tzinfo=UTC) == (
            T0 + timedelta(seconds=15)
        )


def test_reconciler_query_finds_only_expired_reserved_or_submitted_intents() -> None:
    engine, store = _store_fixture()
    with engine.begin() as conn:
        _reserve_btc(conn, store)
        assert store.stale_order_intent_ids(
            conn,
            at_utc=T0 + timedelta(seconds=15),
        ) == ()
        assert store.stale_order_intent_ids(
            conn,
            at_utc=T0 + timedelta(seconds=15, milliseconds=1),
        ) == ("intent-reserve-1",)


def test_phase_a_rejects_already_consumed_signal_without_reserving_cash() -> None:
    engine, store = _store_fixture()
    with engine.begin() as conn:
        store.consume_signal(
            conn,
            signal_key="signal-1",
            order_intent_id="old-intent",
            trade_id="old-trade",
            consumed_at_utc=T0,
        )
        out = _reserve_btc(conn, store)
        assert out["ok"] is False
        assert out["error"] == "signal_consumed"
        ledger = {
            row["broker_account_id"]: row
            for row in store.ledger_rows(conn)
        }["kraken_paper"]
        assert ledger["cash_available_usd"] == pytest.approx(4000.0)
        assert ledger["cash_reserved_usd"] == 0.0


def test_phase_a_rejects_occupied_position_key_without_reserving_cash() -> None:
    engine, store = _store_fixture()
    with engine.begin() as conn:
        store.claim_active_position(
            conn,
            position_key="btc:daily_swing",
            trade_id="old-trade",
            asset_id="btc",
            horizon="daily_swing",
            side="long",
            quantity=0.01,
            updated_at_utc=T0,
        )
        out = _reserve_btc(conn, store)
        assert out["ok"] is False
        assert out["error"] == "duplicate_position_key"
        ledger = {
            row["broker_account_id"]: row
            for row in store.ledger_rows(conn)
        }["kraken_paper"]
        assert ledger["cash_available_usd"] == pytest.approx(4000.0)
        assert ledger["cash_reserved_usd"] == 0.0


def test_reconciler_runs_on_two_second_contract_and_releases_stale_reserve() -> None:
    assert RECONCILER_INTERVAL_SECONDS == 2
    engine, store = _store_fixture()
    with engine.begin() as conn:
        _reserve_btc(conn, store)

    with engine.begin() as conn:
        results = reconcile_stale_intents(
            conn,
            store=store,
            at_utc=T0 + timedelta(seconds=16),
        )
        assert len(results) == 1
        assert results[0]["state"] == "CANCELLED_STALE"

        intent = conn.execute(
            sa.select(store.tables["order_intents"]).where(
                store.tables["order_intents"].c.order_intent_id
                == "intent-reserve-1"
            )
        ).mappings().one()
        assert intent["state"] == "CANCELLED_STALE"
        assert intent["reject_code"] == "submit_timeout"

        ledger = {
            row["broker_account_id"]: row
            for row in store.ledger_rows(conn)
        }["kraken_paper"]
        assert ledger["cash_available_usd"] == pytest.approx(4000.0)
        assert ledger["cash_reserved_usd"] == 0.0
        assert conn.execute(
            sa.select(sa.func.count()).select_from(store.tables["signal_consumptions"])
        ).scalar_one() == 0


def test_late_fill_after_stale_cancel_is_ignored_at_persistence_boundary() -> None:
    engine, store = _store_fixture()
    with engine.begin() as conn:
        _submit_reserved_btc(conn, store)

    with engine.begin() as conn:
        reconcile_stale_intents(
            conn,
            store=store,
            at_utc=T0 + timedelta(seconds=16),
        )

    with engine.begin() as conn:
        late = _finalize_btc(conn, store)
        assert late["ok"] is False
        assert late["duplicate"] is True
        assert late["error"] == "terminal_state_wins"
        assert late["state"] == "CANCELLED_STALE"
        assert conn.execute(
            sa.select(sa.func.count()).select_from(store.tables["open_trades"])
        ).scalar_one() == 0
        assert conn.execute(
            sa.select(sa.func.count()).select_from(store.tables["signal_consumptions"])
        ).scalar_one() == 0


def test_non_stop_flatten_uses_conservative_exit_side_plus_adverse_slip() -> None:
    obs = _obs(bid=99.0, ask=101.0)
    assert exit_fill_price(
        obs,
        position_side="long",
    ) == pytest.approx(99.0 * 0.9995)
    assert exit_fill_price(
        obs,
        position_side="short",
    ) == pytest.approx(101.0 * 1.0005)
