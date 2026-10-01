from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
import sqlalchemy as sa

from aether_vnext.runtime_execution_bridge import submit_runtime_reserved_open
from aether_vnext.runtime_fill_bridge import fill_runtime_submitted_open
from tests_vnext.test_runtime_portfolio_bridge import (
    T0,
    _dynamic_fixture,
    _fixture,
    _reserve,
    _reserve_dynamic,
)


def _submit(
    conn,
    store,
    *,
    order_intent_id: str = "intent-runtime-portfolio",
) -> None:
    result = submit_runtime_reserved_open(
        conn,
        store,
        order_intent_id=order_intent_id,
        submitted_at_utc=T0,
        event_id="evt-runtime-fill-submit",
    )
    assert result["state"] == "SUBMITTED"


def test_runtime_fill_bridge_opens_all_or_none_paper_trade() -> None:
    engine, store, obs = _fixture()
    fill_at = T0 + timedelta(milliseconds=250)
    fill_obs = replace(
        obs,
        observation_id="obs-runtime-fill",
        exchange_ts=fill_at,
        received_ts=fill_at,
    )

    with engine.begin() as conn:
        assert _reserve(conn, store, obs)["state"] == "RESERVED"
        _submit(conn, store)
        store.record_market_observation(conn, fill_obs)

        result = fill_runtime_submitted_open(
            conn,
            store,
            order_intent_id="intent-runtime-portfolio",
            trade_id="trade-runtime-fill",
            fill_market_observation_id=fill_obs.observation_id,
            filled_at_utc=fill_at,
            event_id="evt-runtime-fill",
        )
        intent = store.load_order_intent(
            conn,
            order_intent_id="intent-runtime-portfolio",
        )
        trade = conn.execute(
            sa.select(store.tables["open_trades"]).where(
                store.tables["open_trades"].c.trade_id
                == "trade-runtime-fill"
            )
        ).mappings().one()
        position = conn.execute(
            sa.select(store.tables["active_positions"]).where(
                store.tables["active_positions"].c.trade_id
                == "trade-runtime-fill"
            )
        ).mappings().one()
        pending_risk = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["risk_admission_reservations"]
            )
        ).scalar_one()
        ledger = conn.execute(
            sa.select(store.tables["broker_account_ledgers"]).where(
                store.tables["broker_account_ledgers"].c.broker_account_id
                == "kraken_paper"
            )
        ).mappings().one()

    assert result["ok"] is True
    assert result["state"] == "FILLED"
    assert intent is not None
    assert intent.state.value == "FILLED"
    assert intent.filled_qty == pytest.approx(0.01)
    assert intent.avg_fill_price == pytest.approx(100_060.005)
    assert intent.trade_id == "trade-runtime-fill"
    assert trade["quantity"] == pytest.approx(0.01)
    assert trade["initial_stop_risk_usd"] == pytest.approx(50.60005)
    assert position["position_key"] == "btc:daily_swing"
    assert pending_risk == 0
    assert ledger["cash_reserved_usd"] > 0


def test_runtime_fill_bridge_rejects_market_change_and_releases_reservation() -> None:
    engine, store, obs = _fixture()
    fill_at = T0 + timedelta(milliseconds=250)
    fill_obs = replace(
        obs,
        observation_id="obs-runtime-fill-wide",
        bid=99_900.0,
        ask=100_100.0,
        spread_abs=200.0,
        spread_bps=20.0,
        exchange_ts=fill_at,
        received_ts=fill_at,
    )

    with engine.begin() as conn:
        assert _reserve(conn, store, obs)["state"] == "RESERVED"
        _submit(conn, store)
        store.record_market_observation(conn, fill_obs)

        result = fill_runtime_submitted_open(
            conn,
            store,
            order_intent_id="intent-runtime-portfolio",
            trade_id="trade-runtime-fill-rejected",
            fill_market_observation_id=fill_obs.observation_id,
            filled_at_utc=fill_at,
            event_id="evt-runtime-fill-rejected",
        )
        intent = store.load_order_intent(
            conn,
            order_intent_id="intent-runtime-portfolio",
        )
        ticket = store.load_ticket(
            conn,
            ticket_id="ticket-runtime-portfolio",
        )
        pending_risk = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["risk_admission_reservations"]
            )
        ).scalar_one()
        trade_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["open_trades"]
            )
        ).scalar_one()
        ledger = conn.execute(
            sa.select(store.tables["broker_account_ledgers"]).where(
                store.tables["broker_account_ledgers"].c.broker_account_id
                == "kraken_paper"
            )
        ).mappings().one()

    assert result["state"] == "REJECTED"
    assert intent is not None
    assert intent.state.value == "REJECTED"
    assert intent.reject_code == "market_changed"
    assert ticket is not None
    assert ticket.state.value == "REJECTED"
    assert pending_risk == 0
    assert trade_count == 0
    assert ledger["cash_reserved_usd"] == pytest.approx(0.0)
    assert ledger["cash_available_usd"] == pytest.approx(4_000.0)


def test_runtime_fill_bridge_waits_for_250ms_paper_latency() -> None:
    engine, store, obs = _fixture()
    fill_at = T0 + timedelta(milliseconds=249)
    fill_obs = replace(
        obs,
        observation_id="obs-runtime-fill-early",
        exchange_ts=fill_at,
        received_ts=fill_at,
    )

    with engine.begin() as conn:
        assert _reserve(conn, store, obs)["state"] == "RESERVED"
        _submit(conn, store)
        store.record_market_observation(conn, fill_obs)

        result = fill_runtime_submitted_open(
            conn,
            store,
            order_intent_id="intent-runtime-portfolio",
            trade_id="trade-runtime-fill-early",
            fill_market_observation_id=fill_obs.observation_id,
            filled_at_utc=fill_at,
            event_id="evt-runtime-fill-early",
        )
        intent = store.load_order_intent(
            conn,
            order_intent_id="intent-runtime-portfolio",
        )
        pending_risk = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["risk_admission_reservations"]
            )
        ).scalar_one()

    assert result["ok"] is False
    assert result["reason"] == "paper_latency_wait"
    assert intent is not None
    assert intent.state.value == "SUBMITTED"
    assert pending_risk == 1



def test_runtime_fill_bridge_opens_verified_dynamic_kraken_asset() -> None:
    engine, store, obs = _dynamic_fixture()
    fill_at = T0 + timedelta(milliseconds=250)
    fill_obs = replace(
        obs,
        observation_id="obs-runtime-fill-sol",
        exchange_ts=fill_at,
        received_ts=fill_at,
    )

    with engine.begin() as conn:
        assert _reserve_dynamic(conn, store, obs)["state"] == "RESERVED"
        _submit(
            conn,
            store,
            order_intent_id="intent-runtime-portfolio-sol",
        )
        store.record_market_observation(conn, fill_obs)
        result = fill_runtime_submitted_open(
            conn,
            store,
            order_intent_id="intent-runtime-portfolio-sol",
            trade_id="trade-runtime-fill-sol",
            fill_market_observation_id=fill_obs.observation_id,
            filled_at_utc=fill_at,
            event_id="evt-runtime-fill-sol",
        )
        trade = conn.execute(
            sa.select(store.tables["open_trades"]).where(
                store.tables["open_trades"].c.trade_id
                == "trade-runtime-fill-sol"
            )
        ).mappings().one()
        position = conn.execute(
            sa.select(store.tables["active_positions"]).where(
                store.tables["active_positions"].c.trade_id
                == "trade-runtime-fill-sol"
            )
        ).mappings().one()

    assert result["state"] == "FILLED"
    assert trade["asset_id"] == "kraken:solusd"
    assert trade["broker_account_id"] == "kraken_paper"
    assert position["position_key"] == "kraken:solusd:daily_swing"
    assert position["horizon"] == "daily_swing"
