from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
import sqlalchemy as sa

from aether_vnext.domain import ExitReason
from aether_vnext.runtime_close_execution_bridge import (
    submit_runtime_reserved_close,
)
from aether_vnext.runtime_close_fill_bridge import fill_runtime_submitted_close
from aether_vnext.runtime_close_reserve_bridge import reserve_runtime_flatten
from aether_vnext.runtime_execution_bridge import submit_runtime_reserved_open
from aether_vnext.runtime_exit_request_bridge import request_runtime_flatten
from aether_vnext.runtime_fill_bridge import fill_runtime_submitted_open
from tests_vnext.test_runtime_close_execution_bridge import _reserve_close
from tests_vnext.test_runtime_portfolio_bridge import (
    T0,
    _dynamic_fixture,
    _fixture,
    _reserve_dynamic,
)


def _submitted_close(conn, store, obs) -> None:
    _reserve_close(conn, store, obs)
    result = submit_runtime_reserved_close(
        conn,
        store,
        order_intent_id="intent-runtime-close",
        submitted_at_utc=T0 + timedelta(seconds=2),
        event_id="evt-runtime-close-fill-submit",
    )
    assert result["state"] == "SUBMITTED"


def test_runtime_close_fill_finalizes_open_trade_to_durable_flat() -> None:
    engine, store, obs = _fixture()
    fill_at = T0 + timedelta(seconds=2, milliseconds=250)
    fill_obs = replace(
        obs,
        observation_id="obs-runtime-close-fill",
        bid=101_000.0,
        ask=101_020.0,
        last=101_010.0,
        mark=101_010.0,
        spread_abs=20.0,
        spread_bps=(20.0 / 101_010.0) * 10_000.0,
        exchange_ts=fill_at,
        received_ts=fill_at,
        age_ms=0,
    )

    with engine.begin() as conn:
        _submitted_close(conn, store, obs)
        store.record_market_observation(conn, fill_obs)
        before = conn.execute(
            sa.select(store.tables["broker_account_ledgers"]).where(
                store.tables["broker_account_ledgers"].c.broker_account_id
                == "kraken_paper"
            )
        ).mappings().one()

        result = fill_runtime_submitted_close(
            conn,
            store,
            order_intent_id="intent-runtime-close",
            fill_market_observation_id=fill_obs.observation_id,
            filled_at_utc=fill_at,
            event_id="evt-runtime-close-fill",
        )

        close_intent = store.load_order_intent(
            conn,
            order_intent_id="intent-runtime-close",
        )
        closed = conn.execute(
            sa.select(store.tables["closed_trades"])
        ).mappings().one()
        active_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["active_positions"]
            )
        ).scalar_one()
        retained_open_history_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["open_trades"]
            )
        ).scalar_one()
        after = conn.execute(
            sa.select(store.tables["broker_account_ledgers"]).where(
                store.tables["broker_account_ledgers"].c.broker_account_id
                == "kraken_paper"
            )
        ).mappings().one()

    assert result["ok"] is True
    assert result["state"] == "FLAT"
    assert result["trade_id"] == "trade-runtime-close"
    assert close_intent is not None
    assert close_intent.state.value == "FILLED"
    assert close_intent.filled_qty == pytest.approx(0.01)
    assert close_intent.avg_fill_price is not None
    assert closed["trade_id"] == "trade-runtime-close"
    assert closed["exit_reason"] == "structure"
    assert closed["net_pnl_usd"] < closed["gross_pnl_usd"]
    assert closed["fees_usd"] > 0
    assert closed["total_cost_usd"] >= closed["fees_usd"]
    assert active_count == 0
    # OpenTrade is retained as immutable trade history; active_positions owns
    # current occupancy and closed_trades owns the terminal realized record.
    assert retained_open_history_count == 1
    assert after["cash_reserved_usd"] == pytest.approx(0.0)
    assert after["margin_used_usd"] == pytest.approx(0.0)
    assert after["realized_pnl_usd"] == pytest.approx(
        closed["net_pnl_usd"]
    )
    assert after["fees_accrued_usd"] > before["fees_accrued_usd"]
    assert after["carry_accrued_usd"] == pytest.approx(
        before["carry_accrued_usd"]
    )


def test_runtime_close_fill_retry_is_idempotent_after_flat() -> None:
    engine, store, obs = _fixture()
    fill_at = T0 + timedelta(seconds=2, milliseconds=250)
    fill_obs = replace(
        obs,
        observation_id="obs-runtime-close-fill-retry",
        bid=101_000.0,
        ask=101_020.0,
        last=101_010.0,
        mark=101_010.0,
        spread_abs=20.0,
        spread_bps=(20.0 / 101_010.0) * 10_000.0,
        exchange_ts=fill_at,
        received_ts=fill_at,
        age_ms=0,
    )

    with engine.begin() as conn:
        _submitted_close(conn, store, obs)
        store.record_market_observation(conn, fill_obs)
        first = fill_runtime_submitted_close(
            conn,
            store,
            order_intent_id="intent-runtime-close",
            fill_market_observation_id=fill_obs.observation_id,
            filled_at_utc=fill_at,
            event_id="evt-runtime-close-fill-first",
        )
        second = fill_runtime_submitted_close(
            conn,
            store,
            order_intent_id="intent-runtime-close",
            fill_market_observation_id=fill_obs.observation_id,
            filled_at_utc=fill_at + timedelta(seconds=1),
            event_id="evt-runtime-close-fill-retry",
        )
        closed_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["closed_trades"]
            )
        ).scalar_one()

    assert first["state"] == "FLAT"
    assert second["duplicate"] is True
    assert second["state"] == "FILLED"
    assert second["trade_id"] == "trade-runtime-close"
    assert closed_count == 1


def test_runtime_close_fill_rejection_keeps_position_open() -> None:
    engine, store, obs = _fixture()
    fill_at = T0 + timedelta(seconds=2, milliseconds=250)
    stale_obs = replace(
        obs,
        observation_id="obs-runtime-close-stale",
        exchange_ts=fill_at,
        received_ts=fill_at,
        age_ms=2_000,
    )

    with engine.begin() as conn:
        _submitted_close(conn, store, obs)
        store.record_market_observation(conn, stale_obs)
        result = fill_runtime_submitted_close(
            conn,
            store,
            order_intent_id="intent-runtime-close",
            fill_market_observation_id=stale_obs.observation_id,
            filled_at_utc=fill_at,
            event_id="evt-runtime-close-stale",
        )
        active_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["active_positions"]
            )
        ).scalar_one()
        closed_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["closed_trades"]
            )
        ).scalar_one()
        close_intent = store.load_order_intent(
            conn,
            order_intent_id="intent-runtime-close",
        )

    assert result["state"] == "REJECTED"
    assert close_intent is not None
    assert close_intent.state.value == "REJECTED"
    assert close_intent.reject_code == "market_stale"
    assert active_count == 1
    assert closed_count == 0



def test_verified_dynamic_kraken_trade_round_trips_open_to_flat() -> None:
    engine, store, obs = _dynamic_fixture()
    open_fill_at = T0 + timedelta(milliseconds=250)
    open_fill = replace(
        obs,
        observation_id="obs-dynamic-open-fill",
        exchange_ts=open_fill_at,
        received_ts=open_fill_at,
    )

    with engine.begin() as conn:
        assert _reserve_dynamic(conn, store, obs)["state"] == "RESERVED"
        submitted = submit_runtime_reserved_open(
            conn,
            store,
            order_intent_id="intent-runtime-portfolio-sol",
            submitted_at_utc=T0,
            event_id="evt-dynamic-open-submit",
        )
        assert submitted["state"] == "SUBMITTED"
        store.record_market_observation(conn, open_fill)
        opened = fill_runtime_submitted_open(
            conn,
            store,
            order_intent_id="intent-runtime-portfolio-sol",
            trade_id="trade-dynamic-round-trip",
            fill_market_observation_id=open_fill.observation_id,
            filled_at_utc=open_fill_at,
            event_id="evt-dynamic-open-fill",
        )
        assert opened["state"] == "FILLED"

    close_at = open_fill_at + timedelta(seconds=1)
    close_obs = replace(
        obs,
        observation_id="obs-dynamic-close-reserve",
        bid=151.0,
        ask=151.2,
        last=151.1,
        mark=151.1,
        spread_abs=0.2,
        spread_bps=(0.2 / 151.1) * 10_000.0,
        exchange_ts=close_at,
        received_ts=close_at,
    )
    with engine.begin() as conn:
        store.record_market_observation(conn, close_obs)
        request_runtime_flatten(
            conn,
            store,
            trade_id="trade-dynamic-round-trip",
            exit_reason=ExitReason.STRUCTURE,
            market_observation_id=close_obs.observation_id,
            at_utc=close_at,
            event_id="evt-dynamic-flatten-request",
        )
        reserved = reserve_runtime_flatten(
            conn,
            store,
            order_intent_id="intent-dynamic-close",
            trade_id="trade-dynamic-round-trip",
            idempotency_key="dynamic-close-round-trip",
            exit_reason=ExitReason.STRUCTURE,
            market_observation_id=close_obs.observation_id,
            created_at_utc=close_at,
            event_id="evt-dynamic-close-reserve",
        )
        assert reserved["state"] == "RESERVED"
        submitted = submit_runtime_reserved_close(
            conn,
            store,
            order_intent_id="intent-dynamic-close",
            submitted_at_utc=close_at,
            event_id="evt-dynamic-close-submit",
        )
        assert submitted["state"] == "SUBMITTED"

    close_fill_at = close_at + timedelta(milliseconds=250)
    close_fill = replace(
        close_obs,
        observation_id="obs-dynamic-close-fill",
        exchange_ts=close_fill_at,
        received_ts=close_fill_at,
    )
    with engine.begin() as conn:
        store.record_market_observation(conn, close_fill)
        flattened = fill_runtime_submitted_close(
            conn,
            store,
            order_intent_id="intent-dynamic-close",
            fill_market_observation_id=close_fill.observation_id,
            filled_at_utc=close_fill_at,
            event_id="evt-dynamic-close-fill",
        )
        active_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["active_positions"]
            )
        ).scalar_one()
        closed = conn.execute(
            sa.select(store.tables["closed_trades"]).where(
                store.tables["closed_trades"].c.trade_id
                == "trade-dynamic-round-trip"
            )
        ).mappings().one()

    assert flattened["state"] == "FLAT"
    assert active_count == 0
    assert closed["asset_id"] == "kraken:solusd"
    assert closed["exit_reason"] == "structure"
