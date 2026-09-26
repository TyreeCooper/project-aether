from __future__ import annotations

from datetime import datetime, timezone

import pytest
import sqlalchemy as sa

from aether_vnext.domain import (
    CalendarState,
    MarketObservation,
    QualityState,
    SessionState,
)
from aether_vnext.equity import conservative_unrealized_pnl_usd
from aether_vnext.registry import SEED_REGISTRY
from aether_vnext.reservations import reservation_requirement
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 26, 18, 0, tzinfo=UTC)


def _obs(
    asset_id: str,
    *,
    bid: float,
    ask: float,
    quality: QualityState = QualityState.HEALTHY,
) -> MarketObservation:
    return MarketObservation(
        observation_id=f"obs-{asset_id}",
        asset_id=asset_id,
        venue="paper",
        bid=bid,
        ask=ask,
        last=(bid + ask) / 2.0,
        mark=(bid + ask) / 2.0,
        source="paper-test",
        exchange_ts=T0,
        received_ts=T0,
        age_ms=10,
        spread_abs=ask - bid,
        spread_bps=((ask - bid) / ((ask + bid) / 2.0)) * 10_000.0,
        session_state=SessionState.ACTIVE,
        quality_state=quality,
        fallback_reason=None,
        calendar_state=CalendarState.ALWAYS_OPEN,
        data_version="v1",
    )


def _engine_store():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        assert store.provision_seed_ledgers_once(conn) is True
    return engine, store


def _insert_open_trade(
    conn,
    store: VNextStore,
    *,
    broker_account_id: str,
    asset_id: str,
    side: str,
    quantity: float,
    avg_entry_price: float,
    reserved_cash_usd: float,
    reserved_margin_usd: float,
    horizon: str,
) -> str:
    intent_id = f"intent-{asset_id}"
    trade_id = f"trade-{asset_id}"
    position_key = f"{asset_id}:{horizon}"

    conn.execute(
        store.tables["order_intents"].insert().values(
            order_intent_id=intent_id,
            broker_account_id=broker_account_id,
            exit_plan_id=None,
            intent_kind="OPEN",
            exit_reason=None,
            position_key=position_key,
            signal_key=f"signal-{asset_id}",
            reserved_cash_usd=reserved_cash_usd,
            reserved_margin_usd=reserved_margin_usd,
            ready_spread_bps=2.0,
            hard_stop_price=None,
            submit_timeout_at=None,
            observation_id_at_fill=f"fill-{asset_id}",
            trade_id=trade_id,
            version=1,
            ticket_id=f"ticket-{asset_id}",
            firm_event_id=None,
            asset_id=asset_id,
            route_id=f"{asset_id}:{horizon}:{side}",
            broker=broker_account_id,
            venue="paper",
            symbol_executed=asset_id.upper(),
            side=side,
            requested_qty=quantity,
            order_type="MARKET_PAPER",
            reference_price=avg_entry_price,
            expected_fill_price=avg_entry_price,
            state="FILLED",
            submitted_at=T0,
            acknowledged_at=T0,
            filled_at=T0,
            filled_qty=quantity,
            avg_fill_price=avg_entry_price,
            reject_code=None,
            slip_usd=0.0,
            slip_bps=5.0,
            idempotency_key=f"idem-{asset_id}",
            policy_version="policy-v1",
            configuration_hash="cfg",
            observation_id_at_reserve=f"reserve-{asset_id}",
            first_killed_by=None,
            first_kill_reason=None,
            created_at_utc=T0,
        )
    )
    conn.execute(
        store.tables["open_trades"].insert().values(
            trade_id=trade_id,
            order_intent_id=intent_id,
            ticket_id=f"ticket-{asset_id}",
            setup_id=f"setup-{asset_id}",
            exit_plan_id=f"exit-{asset_id}",
            firm_event_id=None,
            asset_id=asset_id,
            route_id=f"{asset_id}:{horizon}:{side}",
            position_key=position_key,
            side=side,
            quantity=quantity,
            avg_entry_price=avg_entry_price,
            initial_stop_risk_usd=50.0,
            exit_plan_version="v1",
            exit_plan_payload={},
            management_telemetry={},
            policy_version="policy-v1",
            configuration_hash="cfg",
            market_observation_id=f"fill-{asset_id}",
            opened_at_utc=T0,
        )
    )
    conn.execute(
        store.tables["active_positions"].insert().values(
            position_key=position_key,
            trade_id=trade_id,
            asset_id=asset_id,
            horizon=horizon,
            side=side,
            quantity=quantity,
            row_version=1,
            updated_at_utc=T0,
        )
    )
    return trade_id


def test_empty_book_projects_exact_seed_10000() -> None:
    engine, store = _engine_store()
    with engine.begin() as conn:
        projection = store.project_firm_equity(conn, observations={})
    assert projection.consolidated_equity_usd == pytest.approx(10_000.0)
    assert len(projection.sleeves) == 4


def test_btc_open_inventory_projection_removes_purchase_reserve_once() -> None:
    engine, store = _engine_store()
    req = reservation_requirement(
        SEED_REGISTRY["btc"],
        side="long",
        qty=0.01,
        bid=99_990.0,
        ask=100_010.0,
        modeled_round_trip_cost_pct=0.10,
    )

    with engine.begin() as conn:
        ledgers = store.tables["broker_account_ledgers"]
        conn.execute(
            ledgers.update()
            .where(ledgers.c.broker_account_id == "kraken_paper")
            .values(
                cash_available_usd=4000.0 - req.reserve_cash_usd,
                cash_reserved_usd=req.reserve_cash_usd,
            )
        )
        _insert_open_trade(
            conn,
            store,
            broker_account_id="kraken_paper",
            asset_id="btc",
            side="long",
            quantity=0.01,
            avg_entry_price=req.computed_entry_price,
            reserved_cash_usd=req.reserve_cash_usd,
            reserved_margin_usd=0.0,
            horizon="daily_swing",
        )
        conn.execute(
            store.tables["sleeve_inventory"].insert().values(
                broker_account_id="kraken_paper",
                asset_id="btc",
                inventory_qty=0.01,
                inventory_avg=req.computed_entry_price,
                updated_at_utc=T0,
                row_version=1,
            )
        )

        projection = store.project_firm_equity(
            conn,
            observations={"btc": _obs("btc", bid=101_000.0, ask=101_020.0)},
        )

    kraken = next(
        row for row in projection.sleeves
        if row.broker_account_id == "kraken_paper"
    )
    expected_kraken = (
        4000.0 - req.reserve_cash_usd + (0.01 * 101_000.0)
    )
    assert kraken.cash_inventory_backing_reserve_usd == pytest.approx(
        req.reserve_cash_usd
    )
    assert kraken.inventory_mtm_usd == pytest.approx(1010.0)
    assert kraken.sleeve_equity_usd == pytest.approx(expected_kraken)
    assert projection.consolidated_equity_usd == pytest.approx(
        6000.0 + expected_kraken
    )


def test_margin_trade_projection_keeps_reserved_cash_and_marks_unrealized() -> None:
    engine, store = _engine_store()
    req = reservation_requirement(
        SEED_REGISTRY["eurusd"],
        side="long",
        qty=0.10,
        bid=1.08500,
        ask=1.08512,
        modeled_round_trip_cost_pct=(8.40 / 10851.20) * 100.0,
    )
    obs = _obs("eurusd", bid=1.08600, ask=1.08612)
    unrealized = conservative_unrealized_pnl_usd(
        SEED_REGISTRY["eurusd"],
        side="long",
        quantity=0.10,
        avg_entry_price=req.computed_entry_price,
        bid=obs.bid,
        ask=obs.ask,
    )

    with engine.begin() as conn:
        ledgers = store.tables["broker_account_ledgers"]
        conn.execute(
            ledgers.update()
            .where(ledgers.c.broker_account_id == "tastyfx_paper")
            .values(
                cash_available_usd=2000.0 - req.reserve_cash_usd,
                cash_reserved_usd=req.reserve_cash_usd,
                margin_used_usd=req.margin_need_usd,
                margin_available_usd=2000.0 - req.margin_need_usd,
            )
        )
        _insert_open_trade(
            conn,
            store,
            broker_account_id="tastyfx_paper",
            asset_id="eurusd",
            side="long",
            quantity=0.10,
            avg_entry_price=req.computed_entry_price,
            reserved_cash_usd=req.reserve_cash_usd,
            reserved_margin_usd=req.margin_need_usd,
            horizon="swing",
        )

        projection = store.project_firm_equity(
            conn,
            observations={"eurusd": obs},
        )

    tasty = next(
        row for row in projection.sleeves
        if row.broker_account_id == "tastyfx_paper"
    )
    assert tasty.cash_inventory_backing_reserve_usd == 0.0
    assert tasty.inventory_mtm_usd == 0.0
    assert tasty.non_inventory_unrealized_pnl_usd == pytest.approx(unrealized)
    assert tasty.sleeve_equity_usd == pytest.approx(2000.0 + unrealized)


def test_open_asset_without_current_healthy_observation_blocks_projection() -> None:
    engine, store = _engine_store()
    with engine.begin() as conn:
        _insert_open_trade(
            conn,
            store,
            broker_account_id="ninja_paper",
            asset_id="mes",
            side="long",
            quantity=1.0,
            avg_entry_price=6000.0,
            reserved_cash_usd=1201.0,
            reserved_margin_usd=1200.0,
            horizon="intraday",
        )
        with pytest.raises(
            ValueError,
            match="missing current observation for OPEN asset: mes",
        ):
            store.project_firm_equity(conn, observations={})

        with pytest.raises(
            ValueError,
            match="non-healthy observation for OPEN asset: mes",
        ):
            store.project_firm_equity(
                conn,
                observations={
                    "mes": _obs(
                        "mes",
                        bid=6000.0,
                        ask=6000.25,
                        quality=QualityState.STALE,
                    )
                },
            )


def test_inventory_quantity_drift_blocks_projection() -> None:
    engine, store = _engine_store()
    with engine.begin() as conn:
        _insert_open_trade(
            conn,
            store,
            broker_account_id="kraken_paper",
            asset_id="btc",
            side="long",
            quantity=0.01,
            avg_entry_price=100_000.0,
            reserved_cash_usd=1000.0,
            reserved_margin_usd=0.0,
            horizon="daily_swing",
        )
        conn.execute(
            store.tables["broker_account_ledgers"].update()
            .where(
                store.tables["broker_account_ledgers"].c.broker_account_id
                == "kraken_paper"
            )
            .values(
                cash_available_usd=3000.0,
                cash_reserved_usd=1000.0,
            )
        )
        conn.execute(
            store.tables["sleeve_inventory"].insert().values(
                broker_account_id="kraken_paper",
                asset_id="btc",
                inventory_qty=0.02,
                inventory_avg=100_000.0,
                updated_at_utc=T0,
                row_version=1,
            )
        )
        with pytest.raises(
            RuntimeError,
            match="cash inventory quantity drift",
        ):
            store.project_firm_equity(
                conn,
                observations={
                    "btc": _obs("btc", bid=101_000.0, ask=101_020.0)
                },
            )
