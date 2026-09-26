from __future__ import annotations

from dataclasses import replace
import hashlib
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
    Ticket,
    TicketState,
)
from aether_vnext.execution import (
    PAPER_ACK_MS,
    PAPER_SUBMIT_TIMEOUT_MS,
    PaperExecutionPolicy,
    cancel_stale_paper_intent,
    computed_entry_through_protective_stop,
    entry_fill_price,
    exit_fill_price,
    fill_submitted_paper_flatten_intent,
    fill_submitted_paper_intent,
    gross_pnl_usd,
    paper_fill_due_at,
    phase_a_admission,
    stop_exit_fill_price,
    stop_triggered,
    submit_paper_intent,
)
from aether_vnext.reconciler import (
    RECONCILER_INTERVAL_SECONDS,
    reconcile_stale_intents,
)
from aether_vnext.registry import SEED_REGISTRY
from aether_vnext.store import VNextStore, open_intent_idempotency_key


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


def _open_idem(
    *,
    ticket_id: str,
    side: str,
    quantity: float,
    asset_id: str,
    horizon: str,
    signal_key: str,
) -> str:
    return open_intent_idempotency_key(
        ticket_id=ticket_id,
        side=side,
        quantity=quantity,
        asset_id=asset_id,
        horizon=horizon,
        signal_key=signal_key,
    )


def _store_fixture():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        assert store.provision_seed_ledgers_once(conn) is True
        _insert_exit_plan_row(
            conn,
            store,
            exit_plan_id="exit-plan-btc",
            hard_stop_price=95_000.0,
        )
        _insert_exit_plan_row(
            conn,
            store,
            exit_plan_id="exit-plan-mes",
            hard_stop_price=5900.0,
        )
        _insert_ready_ticket_row(
            conn,
            store,
            ticket_id="ticket-1",
            asset_id="btc",
            route_id="btc:daily_swing:long",
            signal_key="signal-1",
            side="long",
            horizon="daily_swing",
            quantity=0.01,
            market_observation_id="obs-ready",
            exit_plan_id="exit-plan-btc",
        )
        _insert_ready_ticket_row(
            conn,
            store,
            ticket_id="ticket-mes",
            asset_id="mes",
            route_id="mes:intraday:long",
            signal_key="signal-mes-1",
            side="long",
            horizon="intraday",
            quantity=1.0,
            stop_price=5900.0,
            market_observation_id="obs-ready-mes",
            exit_plan_id="exit-plan-mes",
        )
    return engine, store


def _reserve_btc(
    conn,
    store: VNextStore,
    *,
    order_intent_id: str = "intent-reserve-1",
    idempotency_key: str | None = None,
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
        idempotency_key=(
            idempotency_key
            or _open_idem(
                ticket_id="ticket-1",
                side="long",
                quantity=0.01,
                asset_id="btc",
                horizon="daily_swing",
                signal_key="signal-1",
            )
        ),
        signal_key="signal-1",
        position_key="btc:daily_swing",
        reserve_cash_usd=reserve_cash_usd,
        reserve_margin_usd=reserve_margin_usd,
        ready_spread_bps=2.0,
        hard_stop_price=95_000.0,
        exit_plan_id="exit-plan-btc",
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
            idempotency_key=_open_idem(
                ticket_id="ticket-mes",
                side="long",
                quantity=1.0,
                asset_id="mes",
                horizon="intraday",
                signal_key="signal-mes-1",
            ),
            signal_key="signal-mes-1",
            position_key="mes:intraday",
            reserve_cash_usd=1201.0,
            reserve_margin_usd=1200.0,
            ready_spread_bps=1.0,
            hard_stop_price=5900.0,
            exit_plan_id="exit-plan-mes",
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
        assert ledger["cash_available_usd"] == pytest.approx(799.0)
        assert ledger["cash_reserved_usd"] == pytest.approx(1201.0)
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
        assert ledger["cash_available_usd"] == pytest.approx(2000.0)
        assert ledger["cash_reserved_usd"] == 0.0
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
        exit_plan_id="exit-plan-btc",
        fill_market_observation_id="obs-fill",
        filled_at_utc=T0 + timedelta(milliseconds=250),
        filled_qty=qty,
        avg_fill_price=100_060.005,
        slippage_usd=0.5,
        slippage_bps=5.0,
        initial_stop_risk_usd=50.0,
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
        assert open_trades[0]["exit_plan_id"] == "exit-plan-btc"

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

        inventory = conn.execute(
            sa.select(store.tables["sleeve_inventory"])
        ).mappings().one()
        assert inventory["broker_account_id"] == "kraken_paper"
        assert inventory["asset_id"] == "btc"
        assert inventory["inventory_qty"] == pytest.approx(0.01)
        assert inventory["inventory_avg"] == pytest.approx(100_060.005)


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


def test_durable_order_intent_round_trips_into_domain_contract() -> None:
    engine, store = _store_fixture()
    with engine.begin() as conn:
        _reserve_btc(conn, store)
        intent = store.load_order_intent(
            conn,
            order_intent_id="intent-reserve-1",
        )
        assert intent is not None
        assert intent.state is OrderIntentState.RESERVED
        assert intent.broker_account_id == "kraken_paper"
        assert intent.position_key == "btc:daily_swing"
        assert intent.signal_key == "signal-1"
        assert intent.reserved_cash_usd == pytest.approx(100.0)
        assert intent.reserved_margin_usd == 0.0
        assert intent.submit_timeout_at is not None
        assert intent.row_version == 1


def _ready_ticket(*, side: str = "long", config: str = "cfg") -> Ticket:
    return Ticket(
        ticket_id="ticket-ready",
        lineage=Lineage(
            asset_id="btc",
            route_id="btc:daily_swing:long",
            policy_version="policy-v1",
            configuration_hash=config,
            market_observation_id="obs-ready",
            created_at_utc=T0,
        ),
        state=TicketState.READY,
        signal_key="signal-ready",
        side=side,
        horizon="daily_swing",
        stop_price=95_000.0,
        quantity=0.01,
        modeled_round_trip_cost_pct=0.1,
        exit_plan_id="exit-plan-btc",
    )


def test_phase_a_admission_accepts_only_ready_healthy_enabled_risk_valid_route() -> None:
    allowed = phase_a_admission(
        ticket=_ready_ticket(),
        observation=_obs(),
        registry_row=SEED_REGISTRY["btc"],
        active_configuration_hash="cfg",
        max_age_ms=1_000,
        route_evidence_state="CANDIDATE",
        route_operational_state="ENABLED",
        governor_halted=False,
        firm_envelope_ok=True,
    )
    assert allowed.allowed is True
    assert allowed.reason == "phase_a_ready"


@pytest.mark.parametrize(
    ("change", "expected"),
    (
        ({"active_configuration_hash": "other"}, "configuration_mismatch"),
        ({"route_evidence_state": "BENCH"}, "route_benched"),
        ({"route_operational_state": "DISABLED"}, "route_halted"),
        ({"governor_halted": True}, "route_halted"),
        ({"firm_envelope_ok": False}, "portfolio_risk_full"),
    ),
)
def test_phase_a_admission_blocks_nonnegotiable_pre_reserve_gates(
    change,
    expected,
) -> None:
    args = dict(
        ticket=_ready_ticket(),
        observation=_obs(),
        registry_row=SEED_REGISTRY["btc"],
        active_configuration_hash="cfg",
        max_age_ms=1_000,
        route_evidence_state="CANDIDATE",
        route_operational_state="ENABLED",
        governor_halted=False,
        firm_envelope_ok=True,
    )
    args.update(change)
    decision = phase_a_admission(**args)
    assert decision.allowed is False
    assert decision.reason == expected


def test_phase_a_admission_blocks_degraded_fallback_and_crypto_short() -> None:
    degraded = phase_a_admission(
        ticket=_ready_ticket(),
        observation=_obs(quality=QualityState.DEGRADED),
        registry_row=SEED_REGISTRY["btc"],
        active_configuration_hash="cfg",
        max_age_ms=1_000,
        route_evidence_state="CANDIDATE",
        route_operational_state="ENABLED",
        governor_halted=False,
        firm_envelope_ok=True,
    )
    assert degraded.allowed is False
    assert degraded.reason == "market_stale"

    short = phase_a_admission(
        ticket=_ready_ticket(side="short"),
        observation=_obs(),
        registry_row=SEED_REGISTRY["btc"],
        active_configuration_hash="cfg",
        max_age_ms=1_000,
        route_evidence_state="CANDIDATE",
        route_operational_state="ENABLED",
        governor_halted=False,
        firm_envelope_ok=True,
    )
    assert short.allowed is False
    assert short.reason == "product_side_unsupported"


def _insert_exit_plan_row(
    conn,
    store: VNextStore,
    *,
    exit_plan_id: str,
    hard_stop_price: float,
) -> None:
    table = store.tables["exit_plans"]
    conn.execute(
        table.insert().values(
            exit_plan_id=exit_plan_id,
            version="v1",
            hard_stop_price=hard_stop_price,
            structure_rule_id=None,
            time_stop_deadline_utc=None,
            trailing_policy={
                "enabled": False,
                "start_condition": None,
                "ratchet_rule": None,
                "never_loosen": True,
            },
            profit_take_policy={
                "enabled": False,
                "rule_id": None,
            },
            session_close_policy="hold",
            stale_mark_policy="hold",
            governor_halt_behavior="hold",
            created_from_playbook_version="1.3",
            payload_hash=f"hash-{exit_plan_id}",
            created_at_utc=T0,
        )
    )


def _insert_ready_ticket_row(
    conn,
    store: VNextStore,
    *,
    ticket_id: str = "ticket-pre",
    asset_id: str = "btc",
    route_id: str = "btc:daily_swing:long",
    signal_key: str = "signal-pre",
    side: str = "long",
    horizon: str = "daily_swing",
    quantity: float = 0.01,
    stop_price: float = 95_000.0,
    market_observation_id: str = "obs-ready",
    exit_plan_id: str = "exit-plan-btc",
) -> None:
    tickets = store.tables["tickets"]
    conn.execute(
        tickets.insert().values(
            ticket_id=ticket_id,
            exit_plan_id=exit_plan_id,
            setup_id=f"setup-{ticket_id}",
            firm_event_id=None,
            asset_id=asset_id,
            route_id=route_id,
            state="READY",
            signal_key=signal_key,
            side=side,
            horizon=horizon,
            stop_price=stop_price,
            quantity=quantity,
            modeled_round_trip_cost_pct=0.1,
            reject_code=None,
            policy_version="policy-v1",
            configuration_hash="cfg",
            market_observation_id=market_observation_id,
            first_killed_by=None,
            first_kill_reason=None,
            created_at_utc=T0,
        )
    )


def test_phase_a_failure_rejects_ticket_without_intent_or_reserve() -> None:
    engine, store = _store_fixture()
    with engine.begin() as conn:
        _insert_ready_ticket_row(conn, store)
        result = store.reject_ticket_pre_reserve(
            conn,
            ticket_id="ticket-pre",
            reason_code="market_stale",
            at_utc=T0,
            event_id="evt-ticket-reject",
            actor="portfolio",
        )
        assert result["state"] == "REJECTED"

        ticket = conn.execute(
            sa.select(store.tables["tickets"]).where(
                store.tables["tickets"].c.ticket_id == "ticket-pre"
            )
        ).mappings().one()
        assert ticket["first_killed_by"] == "Portfolio"
        assert ticket["first_kill_reason"] == "market_stale"
        assert ticket["reject_code"] == "market_stale"

        assert conn.execute(
            sa.select(sa.func.count()).select_from(store.tables["order_intents"])
        ).scalar_one() == 0
        ledger = {
            row["broker_account_id"]: row
            for row in store.ledger_rows(conn)
        }["kraken_paper"]
        assert ledger["cash_available_usd"] == pytest.approx(4000.0)
        assert ledger["cash_reserved_usd"] == 0.0


def test_ready_to_reserved_to_submitted_to_filled_to_open_end_to_end() -> None:
    engine, store = _store_fixture()

    # Phase A: short local DB transaction.
    with engine.begin() as conn:
        reserved = _reserve_btc(conn, store)
        assert reserved["state"] == "RESERVED"

    # Adapter acknowledgement: separate transaction.
    with engine.begin() as conn:
        submitted = store.mark_order_intent_submitted(
            conn,
            order_intent_id="intent-reserve-1",
            submitted_at_utc=T0,
            acknowledged_at_utc=T0,
            submit_timeout_at=None,
            event_id="evt-e2e-submit",
            actor="paper-adapter",
        )
        assert submitted["state"] == "SUBMITTED"

    # Phase B: reload durable intent, wait until the 250 ms event is due, then
    # calculate venue-shaped fill from a fresh observation.
    with engine.begin() as conn:
        durable = store.load_order_intent(
            conn,
            order_intent_id="intent-reserve-1",
        )
        assert durable is not None
        assert durable.state is OrderIntentState.SUBMITTED
        assert durable.submitted_at is not None
        assert durable.submitted_at.tzinfo is not None

    observation = _obs()
    venue_fill = fill_submitted_paper_intent(
        durable,
        observation=observation,
        registry_row=SEED_REGISTRY["btc"],
        ready_spread_bps=2.0,
        hard_stop_price=95_000.0,
        max_age_ms=1_000,
        at_utc=T0 + timedelta(milliseconds=250),
    )
    assert venue_fill.intent.state is OrderIntentState.FILLED

    # Portfolio apply: another short transaction. This is the only step that
    # consumes signal_key and creates OPEN.
    with engine.begin() as conn:
        opened = store.finalize_filled_open(
            conn,
            order_intent_id="intent-reserve-1",
            trade_id="trade-e2e",
            setup_id="setup-ticket-1",
            exit_plan_id="exit-plan-btc",
            fill_market_observation_id="obs-fill",
            filled_at_utc=venue_fill.intent.filled_at,
            filled_qty=venue_fill.intent.filled_qty,
            avg_fill_price=venue_fill.intent.avg_fill_price,
            slippage_usd=venue_fill.intent.slippage_usd or 0.0,
            slippage_bps=venue_fill.intent.slippage_bps or 0.0,
            initial_stop_risk_usd=50.0,
            management_telemetry={},
            event_id="evt-e2e-open",
            actor="portfolio",
        )
        assert opened["state"] == "FILLED"
        assert opened["trade_id"] == "trade-e2e"
        assert conn.execute(
            sa.select(sa.func.count()).select_from(store.tables["open_trades"])
        ).scalar_one() == 1
        assert conn.execute(
            sa.select(sa.func.count()).select_from(store.tables["signal_consumptions"])
        ).scalar_one() == 1


def _submitted_close_intent(
    *,
    side: str = "long",
    exit_reason: str = "structure",
    hard_stop_price: float | None = 95_000.0,
) -> OrderIntent:
    return replace(
        _intent(
            state=OrderIntentState.SUBMITTED,
            side=side,
            submitted_at=T0,
            acknowledged_at=T0,
        ),
        order_intent_id="close-intent-1",
        intent_kind="CLOSE",
        exit_reason=exit_reason,
        hard_stop_price=hard_stop_price,
        position_key="btc:daily_swing",
        signal_key="signal-1",
        trade_id="trade-1",
    )


def test_flatten_fill_uses_conservative_exit_side_and_ignores_wide_spread_gate() -> None:
    intent = _submitted_close_intent()
    obs = _obs(
        bid=99_000.0,
        ask=101_000.0,
        spread_bps=200.0,
    )
    transition = fill_submitted_paper_flatten_intent(
        intent,
        observation=obs,
        registry_row=SEED_REGISTRY["btc"],
        max_age_ms=1_000,
        at_utc=T0 + timedelta(milliseconds=250),
    )
    assert transition.applied is True
    assert transition.intent.state is OrderIntentState.FILLED
    assert transition.intent.avg_fill_price == pytest.approx(
        99_000.0 * 0.9995
    )
    assert transition.intent.filled_qty == intent.qty


def test_hard_stop_flatten_fills_through_gap_not_at_perfect_stop() -> None:
    intent = _submitted_close_intent(
        exit_reason="hard_stop",
        hard_stop_price=95_000.0,
    )
    obs = _obs(
        bid=90_000.0,
        ask=90_020.0,
        spread_bps=2.0,
    )
    transition = fill_submitted_paper_flatten_intent(
        intent,
        observation=obs,
        registry_row=SEED_REGISTRY["btc"],
        max_age_ms=1_000,
        at_utc=T0 + timedelta(milliseconds=250),
    )
    assert transition.intent.state is OrderIntentState.FILLED
    assert transition.intent.avg_fill_price == pytest.approx(
        90_000.0 * 0.9995
    )
    assert transition.intent.avg_fill_price < 95_000.0


def test_flatten_rejects_stale_observation_but_does_not_consume_position() -> None:
    intent = _submitted_close_intent()
    transition = fill_submitted_paper_flatten_intent(
        intent,
        observation=_obs(quality=QualityState.STALE),
        registry_row=SEED_REGISTRY["btc"],
        max_age_ms=1_000,
        at_utc=T0 + timedelta(milliseconds=250),
    )
    assert transition.intent.state is OrderIntentState.REJECTED
    assert transition.intent.reject_code == "market_stale"


def test_flatten_requires_close_intent_kind() -> None:
    entry_intent = replace(
        _intent(
            state=OrderIntentState.SUBMITTED,
            submitted_at=T0,
            acknowledged_at=T0,
        ),
        intent_kind="OPEN",
    )
    transition = fill_submitted_paper_flatten_intent(
        entry_intent,
        observation=_obs(),
        registry_row=SEED_REGISTRY["btc"],
        max_age_ms=1_000,
        at_utc=T0 + timedelta(milliseconds=250),
    )
    assert transition.applied is False
    assert transition.reason == "illegal_intent_kind"


def test_product_correct_gross_pnl_uses_actual_fill_prices() -> None:
    assert gross_pnl_usd(
        SEED_REGISTRY["btc"],
        position_side="long",
        qty=0.01,
        entry_price=100_000.0,
        exit_price=101_000.0,
    ) == pytest.approx(10.0)

    assert gross_pnl_usd(
        SEED_REGISTRY["mes"],
        position_side="long",
        qty=1.0,
        entry_price=6000.0,
        exit_price=6005.0,
    ) == pytest.approx(25.0)

    assert gross_pnl_usd(
        SEED_REGISTRY["eurusd"],
        position_side="long",
        qty=0.10,
        entry_price=1.0800,
        exit_price=1.0810,
    ) == pytest.approx(10.0)

    usdjpy = gross_pnl_usd(
        SEED_REGISTRY["usdjpy"],
        position_side="long",
        qty=0.10,
        entry_price=150.00,
        exit_price=150.10,
    )
    assert usdjpy == pytest.approx(
        (0.10 * 0.10 * 100_000.0) / 150.10
    )


def test_gross_pnl_direction_reverses_for_short() -> None:
    profit = gross_pnl_usd(
        SEED_REGISTRY["nvda"],
        position_side="short",
        qty=10,
        entry_price=100.0,
        exit_price=95.0,
    )
    assert profit == pytest.approx(50.0)


def _open_btc_for_flatten(conn, store: VNextStore) -> None:
    _submit_reserved_btc(conn, store)
    opened = _finalize_btc(conn, store)
    assert opened["ok"] is True
    assert opened["state"] == "FILLED"


def test_flatten_request_and_reserve_do_not_touch_open_reservation() -> None:
    engine, store = _store_fixture()
    with engine.begin() as conn:
        _open_btc_for_flatten(conn, store)
        before = {
            row["broker_account_id"]: row
            for row in store.ledger_rows(conn)
        }["kraken_paper"]

        requested = store.request_flatten(
            conn,
            trade_id="trade-1",
            exit_reason="structure",
            market_observation_id="obs-exit-request",
            at_utc=T0 + timedelta(seconds=1),
            event_id="evt-flat-request-1",
        )
        assert requested["state"] == "FLATTEN_REQUEST"

        reserved = store.reserve_flatten_intent(
            conn,
            order_intent_id="close-intent-1",
            trade_id="trade-1",
            idempotency_key="close-idem-1",
            exit_reason="structure",
            market_observation_id="obs-exit-request",
            reference_price=101_000.0,
            ready_spread_bps=2.0,
            created_at_utc=T0 + timedelta(seconds=1),
            event_id="evt-flat-reserve-1",
        )
        assert reserved["state"] == "RESERVED"

        after = {
            row["broker_account_id"]: row
            for row in store.ledger_rows(conn)
        }["kraken_paper"]
        assert after["cash_available_usd"] == pytest.approx(
            before["cash_available_usd"]
        )
        assert after["cash_reserved_usd"] == pytest.approx(
            before["cash_reserved_usd"]
        )

        close_intent = store.load_order_intent(
            conn,
            order_intent_id="close-intent-1",
        )
        assert close_intent is not None
        assert close_intent.intent_kind == "CLOSE"
        assert close_intent.exit_reason == "structure"
        assert close_intent.reserved_cash_usd == 0.0
        assert close_intent.reserved_margin_usd == 0.0
        assert close_intent.trade_id == "trade-1"


def test_full_flatten_lifecycle_books_closed_trade_and_releases_reserve_once() -> None:
    engine, store = _store_fixture()
    with engine.begin() as conn:
        _open_btc_for_flatten(conn, store)
        store.request_flatten(
            conn,
            trade_id="trade-1",
            exit_reason="structure",
            market_observation_id="obs-exit-request",
            at_utc=T0 + timedelta(seconds=1),
            event_id="evt-flat-request-2",
        )
        store.reserve_flatten_intent(
            conn,
            order_intent_id="close-intent-2",
            trade_id="trade-1",
            idempotency_key="close-idem-2",
            exit_reason="structure",
            market_observation_id="obs-exit-request",
            reference_price=101_000.0,
            ready_spread_bps=2.0,
            created_at_utc=T0 + timedelta(seconds=1),
            event_id="evt-flat-reserve-2",
        )

    with engine.begin() as conn:
        store.mark_order_intent_submitted(
            conn,
            order_intent_id="close-intent-2",
            submitted_at_utc=T0 + timedelta(seconds=1),
            acknowledged_at_utc=T0 + timedelta(seconds=1),
            submit_timeout_at=None,
            event_id="evt-flat-submit-2",
            actor="paper-adapter",
        )
        durable = store.load_order_intent(
            conn,
            order_intent_id="close-intent-2",
        )
        assert durable is not None
        assert durable.state is OrderIntentState.SUBMITTED

    observation = _obs(
        bid=101_000.0,
        ask=101_020.0,
        spread_bps=2.0,
    )
    venue_fill = fill_submitted_paper_flatten_intent(
        durable,
        observation=observation,
        registry_row=SEED_REGISTRY["btc"],
        max_age_ms=1_000,
        at_utc=T0 + timedelta(seconds=1, milliseconds=250),
    )
    assert venue_fill.intent.state is OrderIntentState.FILLED
    exit_price = float(venue_fill.intent.avg_fill_price)

    entry_price = 100_060.005
    gross = gross_pnl_usd(
        SEED_REGISTRY["btc"],
        position_side="long",
        qty=0.01,
        entry_price=entry_price,
        exit_price=exit_price,
    )
    fees = 2.0
    net = gross - fees

    with engine.begin() as conn:
        flat = store.finalize_filled_flat(
            conn,
            close_order_intent_id="close-intent-2",
            fill_market_observation_id="obs-exit-fill",
            filled_at_utc=venue_fill.intent.filled_at,
            filled_qty=venue_fill.intent.filled_qty,
            exit_price=exit_price,
            gross_pnl_usd=gross,
            net_pnl_usd=net,
            total_cost_usd=fees + float(venue_fill.intent.slippage_usd or 0.0),
            fees_usd=fees,
            slippage_usd=float(venue_fill.intent.slippage_usd or 0.0),
            slippage_bps=float(venue_fill.intent.slippage_bps or 0.0),
            mfe_usd=12.0,
            mae_usd=-3.0,
            capture_efficiency=0.75,
            event_id="evt-flat-final-2",
        )
        assert flat["ok"] is True
        assert flat["state"] == "FLAT"

        closed = conn.execute(
            sa.select(store.tables["closed_trades"])
        ).mappings().one()
        assert closed["trade_id"] == "trade-1"
        assert closed["asset_id"] == "btc"
        assert closed["position_key"] == "btc:daily_swing"
        assert closed["side"] == "long"
        assert closed["quantity"] == pytest.approx(0.01)
        assert closed["avg_entry_price"] == pytest.approx(entry_price)
        assert closed["exit_price"] == pytest.approx(exit_price)
        assert closed["gross_pnl_usd"] == pytest.approx(gross)
        assert closed["net_pnl_usd"] == pytest.approx(net)
        assert closed["fees_usd"] == pytest.approx(fees)
        assert closed["exit_reason"] == "structure"

        assert conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["active_positions"]
            )
        ).scalar_one() == 0
        assert conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["signal_consumptions"]
            )
        ).scalar_one() == 1
        assert conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["sleeve_inventory"]
            )
        ).scalar_one() == 0

        ledger = {
            row["broker_account_id"]: row
            for row in store.ledger_rows(conn)
        }["kraken_paper"]
        assert ledger["cash_reserved_usd"] == 0.0
        assert ledger["cash_available_usd"] == pytest.approx(4000.0 + net)
        assert ledger["realized_pnl_usd"] == pytest.approx(net)
        assert ledger["fees_accrued_usd"] == pytest.approx(fees)

    with engine.begin() as conn:
        duplicate = store.finalize_filled_flat(
            conn,
            close_order_intent_id="close-intent-2",
            fill_market_observation_id="obs-exit-fill",
            filled_at_utc=venue_fill.intent.filled_at,
            filled_qty=venue_fill.intent.filled_qty,
            exit_price=exit_price,
            gross_pnl_usd=gross,
            net_pnl_usd=net,
            total_cost_usd=fees + float(venue_fill.intent.slippage_usd or 0.0),
            fees_usd=fees,
            slippage_usd=float(venue_fill.intent.slippage_usd or 0.0),
            slippage_bps=float(venue_fill.intent.slippage_bps or 0.0),
            mfe_usd=12.0,
            mae_usd=-3.0,
            capture_efficiency=0.75,
            event_id="evt-flat-final-duplicate",
        )
        assert duplicate["duplicate"] is True
        ledger = {
            row["broker_account_id"]: row
            for row in store.ledger_rows(conn)
        }["kraken_paper"]
        assert ledger["cash_available_usd"] == pytest.approx(4000.0 + net)
        assert ledger["realized_pnl_usd"] == pytest.approx(net)


def test_rejected_close_releases_no_open_reserve_and_keeps_position_open() -> None:
    engine, store = _store_fixture()
    with engine.begin() as conn:
        _open_btc_for_flatten(conn, store)
        store.request_flatten(
            conn,
            trade_id="trade-1",
            exit_reason="structure",
            market_observation_id="obs-exit-request",
            at_utc=T0 + timedelta(seconds=1),
            event_id="evt-flat-request-3",
        )
        store.reserve_flatten_intent(
            conn,
            order_intent_id="close-intent-3",
            trade_id="trade-1",
            idempotency_key="close-idem-3",
            exit_reason="structure",
            market_observation_id="obs-exit-request",
            reference_price=101_000.0,
            ready_spread_bps=2.0,
            created_at_utc=T0 + timedelta(seconds=1),
            event_id="evt-flat-reserve-3",
        )
        store.mark_order_intent_submitted(
            conn,
            order_intent_id="close-intent-3",
            submitted_at_utc=T0 + timedelta(seconds=1),
            acknowledged_at_utc=T0 + timedelta(seconds=1),
            submit_timeout_at=None,
            event_id="evt-flat-submit-3",
            actor="paper-adapter",
        )
        store.release_order_reservation(
            conn,
            order_intent_id="close-intent-3",
            terminal_state="REJECTED",
            reject_code="market_stale",
            at_utc=T0 + timedelta(seconds=2),
            event_id="evt-flat-reject-3",
            actor="paper-adapter",
        )

        ledger = {
            row["broker_account_id"]: row
            for row in store.ledger_rows(conn)
        }["kraken_paper"]
        assert ledger["cash_available_usd"] == pytest.approx(3900.0)
        assert ledger["cash_reserved_usd"] == pytest.approx(100.0)
        assert conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["active_positions"]
            )
        ).scalar_one() == 1
        assert conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["closed_trades"]
            )
        ).scalar_one() == 0
        assert conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["signal_consumptions"]
            )
        ).scalar_one() == 1


def test_margin_reservation_cannot_exist_without_matching_cash_reserve() -> None:
    engine, store = _store_fixture()
    with engine.begin() as conn:
        with pytest.raises(
            ValueError,
            match="reserve_cash_usd must include at least the locked margin",
        ):
            store.reserve_order_intent(
                conn,
                order_intent_id="intent-mes-invalid",
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
                idempotency_key=_open_idem(
                    ticket_id="ticket-mes",
                    side="long",
                    quantity=1.0,
                    asset_id="mes",
                    horizon="intraday",
                    signal_key="signal-mes-1",
                ),
                signal_key="signal-mes-1",
                position_key="mes:intraday",
                reserve_cash_usd=100.0,
                reserve_margin_usd=1200.0,
                ready_spread_bps=1.0,
                hard_stop_price=5900.0,
                exit_plan_id="exit-plan-mes",
                submit_timeout_at=None,
                policy_version="policy-v1",
                configuration_hash="cfg",
                market_observation_id="obs-ready-mes",
                created_at_utc=T0,
                event_id="evt-mes-invalid",
                actor="test",
            )


def test_futures_open_to_flat_releases_cash_and_margin_and_books_net() -> None:
    engine, store = _store_fixture()

    with engine.begin() as conn:
        reserved = store.reserve_order_intent(
            conn,
            order_intent_id="intent-mes-open",
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
            idempotency_key=_open_idem(
                ticket_id="ticket-mes",
                side="long",
                quantity=1.0,
                asset_id="mes",
                horizon="intraday",
                signal_key="signal-mes-1",
            ),
            signal_key="signal-mes-1",
            position_key="mes:intraday",
            reserve_cash_usd=1201.0,
            reserve_margin_usd=1200.0,
            ready_spread_bps=1.0,
            hard_stop_price=5900.0,
            exit_plan_id="exit-plan-mes",
            submit_timeout_at=None,
            policy_version="policy-v1",
            configuration_hash="cfg",
            market_observation_id="obs-ready-mes",
            created_at_utc=T0,
            event_id="evt-mes-open-reserve",
            actor="test",
        )
        assert reserved["state"] == "RESERVED"
        store.mark_order_intent_submitted(
            conn,
            order_intent_id="intent-mes-open",
            submitted_at_utc=T0,
            acknowledged_at_utc=T0,
            submit_timeout_at=None,
            event_id="evt-mes-open-submit",
            actor="paper-adapter",
        )
        opened = store.finalize_filled_open(
            conn,
            order_intent_id="intent-mes-open",
            trade_id="trade-mes",
            setup_id="setup-ticket-mes",
            exit_plan_id="exit-plan-mes",
            fill_market_observation_id="obs-fill-mes",
            filled_at_utc=T0 + timedelta(milliseconds=250),
            filled_qty=1.0,
            avg_fill_price=6003.0,
            slippage_usd=1.0,
            slippage_bps=5.0,
            initial_stop_risk_usd=100.0,
            management_telemetry={},
            event_id="evt-mes-open-final",
            actor="paper-adapter",
        )
        assert opened["state"] == "FILLED"

        ledger = {
            row["broker_account_id"]: row
            for row in store.ledger_rows(conn)
        }["ninja_paper"]
        assert ledger["cash_available_usd"] == pytest.approx(799.0)
        assert ledger["cash_reserved_usd"] == pytest.approx(1201.0)
        assert ledger["margin_used_usd"] == pytest.approx(1200.0)
        assert ledger["margin_available_usd"] == pytest.approx(800.0)
        assert conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["sleeve_inventory"]
            )
        ).scalar_one() == 0

        store.request_flatten(
            conn,
            trade_id="trade-mes",
            exit_reason="structure",
            market_observation_id="obs-mes-exit-request",
            at_utc=T0 + timedelta(seconds=1),
            event_id="evt-mes-flat-request",
        )
        store.reserve_flatten_intent(
            conn,
            order_intent_id="intent-mes-close",
            trade_id="trade-mes",
            idempotency_key="idem-mes-close",
            exit_reason="structure",
            market_observation_id="obs-mes-exit-request",
            reference_price=6008.0,
            ready_spread_bps=1.0,
            created_at_utc=T0 + timedelta(seconds=1),
            event_id="evt-mes-flat-reserve",
        )
        store.mark_order_intent_submitted(
            conn,
            order_intent_id="intent-mes-close",
            submitted_at_utc=T0 + timedelta(seconds=1),
            acknowledged_at_utc=T0 + timedelta(seconds=1),
            submit_timeout_at=None,
            event_id="evt-mes-flat-submit",
            actor="paper-adapter",
        )
        close_intent = store.load_order_intent(
            conn,
            order_intent_id="intent-mes-close",
        )
        assert close_intent is not None

    mes_obs = replace(
        _obs(
            bid=6008.0,
            ask=6008.25,
            spread_bps=0.42,
        ),
        observation_id="obs-mes-exit-fill",
        asset_id="mes",
        venue="NinjaTrader",
        source="ninja-paper",
        mark=6008.125,
    )
    venue_fill = fill_submitted_paper_flatten_intent(
        close_intent,
        observation=mes_obs,
        registry_row=SEED_REGISTRY["mes"],
        max_age_ms=1_000,
        at_utc=T0 + timedelta(seconds=1, milliseconds=250),
    )
    assert venue_fill.intent.state is OrderIntentState.FILLED

    exit_price = float(venue_fill.intent.avg_fill_price)
    gross = gross_pnl_usd(
        SEED_REGISTRY["mes"],
        position_side="long",
        qty=1.0,
        entry_price=6003.0,
        exit_price=exit_price,
    )
    fees = 1.0
    net = gross - fees

    with engine.begin() as conn:
        flat = store.finalize_filled_flat(
            conn,
            close_order_intent_id="intent-mes-close",
            fill_market_observation_id="obs-mes-exit-fill",
            filled_at_utc=venue_fill.intent.filled_at,
            filled_qty=venue_fill.intent.filled_qty,
            exit_price=exit_price,
            gross_pnl_usd=gross,
            net_pnl_usd=net,
            total_cost_usd=fees + float(venue_fill.intent.slippage_usd or 0.0),
            fees_usd=fees,
            slippage_usd=float(venue_fill.intent.slippage_usd or 0.0),
            slippage_bps=float(venue_fill.intent.slippage_bps or 0.0),
            mfe_usd=30.0,
            mae_usd=-10.0,
            capture_efficiency=0.50,
            event_id="evt-mes-flat-final",
        )
        assert flat["state"] == "FLAT"

        ledger = {
            row["broker_account_id"]: row
            for row in store.ledger_rows(conn)
        }["ninja_paper"]
        assert ledger["cash_reserved_usd"] == 0.0
        assert ledger["margin_used_usd"] == 0.0
        assert ledger["margin_available_usd"] == pytest.approx(2000.0)
        assert ledger["cash_available_usd"] == pytest.approx(2000.0 + net)
        assert ledger["realized_pnl_usd"] == pytest.approx(net)
        assert conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["active_positions"]
            )
        ).scalar_one() == 0
        assert conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["signal_consumptions"]
            )
        ).scalar_one() == 1


def test_bad_fill_through_stop_erratum_uses_protective_loss_direction() -> None:
    assert computed_entry_through_protective_stop(
        position_side="long",
        computed_fill_price=94_999.0,
        hard_stop_price=95_000.0,
    ) is True
    assert computed_entry_through_protective_stop(
        position_side="long",
        computed_fill_price=95_001.0,
        hard_stop_price=95_000.0,
    ) is False

    assert computed_entry_through_protective_stop(
        position_side="short",
        computed_fill_price=105_001.0,
        hard_stop_price=105_000.0,
    ) is True
    assert computed_entry_through_protective_stop(
        position_side="short",
        computed_fill_price=104_999.0,
        hard_stop_price=105_000.0,
    ) is False


def test_normal_long_entry_above_protective_stop_is_not_bad_fill() -> None:
    submitted = submit_paper_intent(_intent(), at_utc=T0).intent
    transition = fill_submitted_paper_intent(
        submitted,
        observation=_obs(),
        registry_row=SEED_REGISTRY["btc"],
        ready_spread_bps=2.0,
        hard_stop_price=95_000.0,
        max_age_ms=1_000,
        at_utc=T0 + timedelta(milliseconds=250),
    )
    assert transition.intent.state is OrderIntentState.FILLED
    assert transition.intent.reject_code is None


def test_conservative_stop_through_keeps_market_changed_precedence() -> None:
    submitted = submit_paper_intent(_intent(), at_utc=T0).intent
    transition = fill_submitted_paper_intent(
        submitted,
        observation=_obs(bid=94_900.0, ask=94_920.0),
        registry_row=SEED_REGISTRY["btc"],
        ready_spread_bps=3.0,
        hard_stop_price=95_000.0,
        max_age_ms=1_000,
        at_utc=T0 + timedelta(milliseconds=250),
    )
    assert transition.intent.state is OrderIntentState.REJECTED
    assert transition.intent.reject_code == "market_changed"


def test_kraken_btc_and_eth_inventory_rows_never_mix_units_or_average_price() -> None:
    engine, store = _store_fixture()

    with engine.begin() as conn:
        _insert_exit_plan_row(
            conn,
            store,
            exit_plan_id="exit-plan-eth",
            hard_stop_price=3800.0,
        )
        _insert_ready_ticket_row(
            conn,
            store,
            ticket_id="ticket-eth",
            asset_id="eth",
            route_id="eth:daily_swing:long",
            signal_key="signal-eth-1",
            side="long",
            horizon="daily_swing",
            quantity=0.02,
            stop_price=3800.0,
            market_observation_id="obs-ready-eth",
            exit_plan_id="exit-plan-eth",
        )

        _submit_reserved_btc(conn, store)
        btc_open = _finalize_btc(conn, store)
        assert btc_open["state"] == "FILLED"

        eth_reserved = store.reserve_order_intent(
            conn,
            order_intent_id="intent-eth-open",
            ticket_id="ticket-eth",
            firm_event_id=None,
            asset_id="eth",
            route_id="eth:daily_swing:long",
            broker_account_id="kraken_paper",
            broker="Kraken",
            venue="Kraken",
            symbol="ETHUSD",
            side="long",
            qty=0.02,
            order_type="market",
            reference_price=4000.0,
            expected_fill=4002.0,
            idempotency_key=_open_idem(
                ticket_id="ticket-eth",
                side="long",
                quantity=0.02,
                asset_id="eth",
                horizon="daily_swing",
                signal_key="signal-eth-1",
            ),
            signal_key="signal-eth-1",
            position_key="eth:daily_swing",
            reserve_cash_usd=80.0,
            reserve_margin_usd=0.0,
            ready_spread_bps=2.0,
            hard_stop_price=3800.0,
            exit_plan_id="exit-plan-eth",
            submit_timeout_at=None,
            policy_version="policy-v1",
            configuration_hash="cfg",
            market_observation_id="obs-ready-eth",
            created_at_utc=T0,
            event_id="evt-eth-reserve",
            actor="test",
        )
        assert eth_reserved["state"] == "RESERVED"

        store.mark_order_intent_submitted(
            conn,
            order_intent_id="intent-eth-open",
            submitted_at_utc=T0,
            acknowledged_at_utc=T0,
            submit_timeout_at=None,
            event_id="evt-eth-submit",
            actor="paper-adapter",
        )
        eth_open = store.finalize_filled_open(
            conn,
            order_intent_id="intent-eth-open",
            trade_id="trade-eth",
            setup_id="setup-ticket-eth",
            exit_plan_id="exit-plan-eth",
            fill_market_observation_id="obs-fill-eth",
            filled_at_utc=T0 + timedelta(milliseconds=250),
            filled_qty=0.02,
            avg_fill_price=4002.0,
            slippage_usd=0.04,
            slippage_bps=5.0,
            initial_stop_risk_usd=4.04,
            management_telemetry={},
            event_id="evt-eth-open",
            actor="paper-adapter",
        )
        assert eth_open["state"] == "FILLED"

        rows = conn.execute(
            sa.select(store.tables["sleeve_inventory"]).order_by(
                store.tables["sleeve_inventory"].c.asset_id
            )
        ).mappings().all()
        assert len(rows) == 2
        by_asset = {row["asset_id"]: row for row in rows}
        assert set(by_asset) == {"btc", "eth"}
        assert by_asset["btc"]["broker_account_id"] == "kraken_paper"
        assert by_asset["eth"]["broker_account_id"] == "kraken_paper"
        assert by_asset["btc"]["inventory_qty"] == pytest.approx(0.01)
        assert by_asset["btc"]["inventory_avg"] == pytest.approx(100_060.005)
        assert by_asset["eth"]["inventory_qty"] == pytest.approx(0.02)
        assert by_asset["eth"]["inventory_avg"] == pytest.approx(4002.0)


def test_open_idempotency_key_matches_binding_formula_exactly() -> None:
    expected = hashlib.sha256(
        b"ticket-1|long|0.01|btc|daily_swing|signal-1"
    ).hexdigest()
    assert _open_idem(
        ticket_id="ticket-1",
        side="long",
        quantity=0.01,
        asset_id="btc",
        horizon="daily_swing",
        signal_key="signal-1",
    ) == expected


def test_phase_a_rejects_noncanonical_idempotency_key_without_reserving() -> None:
    engine, store = _store_fixture()
    with engine.begin() as conn:
        result = _reserve_btc(
            conn,
            store,
            idempotency_key="caller-invented-key",
        )
        assert result["ok"] is False
        assert result["error"] == "idempotency_key_mismatch"
        assert conn.execute(
            sa.select(sa.func.count()).select_from(store.tables["order_intents"])
        ).scalar_one() == 0
        ledger = {
            row["broker_account_id"]: row
            for row in store.ledger_rows(conn)
        }["kraken_paper"]
        assert ledger["cash_available_usd"] == pytest.approx(4000.0)
        assert ledger["cash_reserved_usd"] == 0.0


def test_phase_a_rejects_wrong_broker_sleeve_without_reserving() -> None:
    engine, store = _store_fixture()
    with engine.begin() as conn:
        result = store.reserve_order_intent(
            conn,
            order_intent_id="intent-wrong-sleeve",
            ticket_id="ticket-1",
            firm_event_id=None,
            asset_id="btc",
            route_id="btc:daily_swing:long",
            broker_account_id="ibkr_paper",
            broker="Kraken",
            venue="Kraken",
            symbol="XBTUSD",
            side="long",
            qty=0.01,
            order_type="market",
            reference_price=100_000.0,
            expected_fill=100_060.0,
            idempotency_key=_open_idem(
                ticket_id="ticket-1",
                side="long",
                quantity=0.01,
                asset_id="btc",
                horizon="daily_swing",
                signal_key="signal-1",
            ),
            signal_key="signal-1",
            position_key="btc:daily_swing",
            reserve_cash_usd=100.0,
            reserve_margin_usd=0.0,
            ready_spread_bps=2.0,
            hard_stop_price=95_000.0,
            exit_plan_id="exit-plan-btc",
            submit_timeout_at=None,
            policy_version="policy-v1",
            configuration_hash="cfg",
            market_observation_id="obs-ready",
            created_at_utc=T0,
            event_id="evt-wrong-sleeve",
            actor="test",
        )
        assert result["ok"] is False
        assert result["error"] == "broker_sleeve_mismatch"
        assert conn.execute(
            sa.select(sa.func.count()).select_from(store.tables["order_intents"])
        ).scalar_one() == 0
        ledgers = {
            row["broker_account_id"]: row
            for row in store.ledger_rows(conn)
        }
        assert ledgers["kraken_paper"]["cash_available_usd"] == pytest.approx(4000.0)
        assert ledgers["ibkr_paper"]["cash_available_usd"] == pytest.approx(2000.0)
