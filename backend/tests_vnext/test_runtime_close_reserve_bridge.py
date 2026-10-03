from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
import sqlalchemy as sa

from aether_vnext.exit_plan import ExitReason
from aether_vnext.runtime_close_reserve_bridge import reserve_runtime_flatten
from aether_vnext.runtime_execution_bridge import submit_runtime_reserved_open
from aether_vnext.runtime_exit_request_bridge import request_runtime_flatten
from aether_vnext.runtime_fill_bridge import fill_runtime_submitted_open
from tests_vnext.test_runtime_portfolio_bridge import T0, _fixture, _reserve


def _open_and_request(conn, store, obs) -> str:
    assert _reserve(conn, store, obs)["state"] == "RESERVED"
    assert submit_runtime_reserved_open(
        conn,
        store,
        order_intent_id="intent-runtime-portfolio",
        submitted_at_utc=T0,
        event_id="evt-runtime-close-submit-open",
    )["state"] == "SUBMITTED"

    fill_at = T0 + timedelta(milliseconds=250)
    fill_obs = replace(
        obs,
        observation_id="obs-runtime-close-open",
        exchange_ts=fill_at,
        received_ts=fill_at,
    )
    store.record_market_observation(conn, fill_obs)
    assert fill_runtime_submitted_open(
        conn,
        store,
        order_intent_id="intent-runtime-portfolio",
        trade_id="trade-runtime-close",
        fill_market_observation_id=fill_obs.observation_id,
        filled_at_utc=fill_at,
        event_id="evt-runtime-close-open",
    )["state"] == "FILLED"

    assert request_runtime_flatten(
        conn,
        store,
        trade_id="trade-runtime-close",
        exit_reason=ExitReason.STRUCTURE,
        market_observation_id=fill_obs.observation_id,
        at_utc=T0 + timedelta(seconds=1),
        event_id="evt-runtime-close-request",
    )["state"] == "FLATTEN_REQUEST"
    return fill_obs.observation_id


def _reserve_close(conn, store, observation_id: str):
    return reserve_runtime_flatten(
        conn,
        store,
        order_intent_id="intent-runtime-close",
        trade_id="trade-runtime-close",
        idempotency_key="idem-runtime-close",
        exit_reason=ExitReason.STRUCTURE,
        market_observation_id=observation_id,
        created_at_utc=T0 + timedelta(seconds=1),
        event_id="evt-runtime-close-reserve",
    )


def test_runtime_close_reserve_creates_zero_capital_close_intent() -> None:
    engine, store, obs = _fixture()
    with engine.begin() as conn:
        observation_id = _open_and_request(conn, store, obs)
        before = conn.execute(
            sa.select(store.tables["broker_account_ledgers"]).where(
                store.tables["broker_account_ledgers"].c.broker_account_id
                == "kraken_paper"
            )
        ).mappings().one()

        result = _reserve_close(conn, store, observation_id)
        close_intent = store.load_order_intent(
            conn,
            order_intent_id="intent-runtime-close",
        )
        after = conn.execute(
            sa.select(store.tables["broker_account_ledgers"]).where(
                store.tables["broker_account_ledgers"].c.broker_account_id
                == "kraken_paper"
            )
        ).mappings().one()
        active_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["active_positions"]
            )
        ).scalar_one()

    assert result["ok"] is True
    assert result["state"] == "RESERVED"
    assert close_intent is not None
    assert close_intent.intent_kind == "CLOSE"
    assert close_intent.exit_reason == "structure"
    assert close_intent.reserved_cash_usd == pytest.approx(0.0)
    assert close_intent.reserved_margin_usd == pytest.approx(0.0)
    assert close_intent.requested_qty == pytest.approx(0.01)
    assert close_intent.trade_id == "trade-runtime-close"
    assert after["cash_reserved_usd"] == pytest.approx(before["cash_reserved_usd"])
    assert after["margin_used_usd"] == pytest.approx(before["margin_used_usd"])
    assert active_count == 1


def test_runtime_close_reserve_is_idempotent_for_supplied_key() -> None:
    engine, store, obs = _fixture()
    with engine.begin() as conn:
        observation_id = _open_and_request(conn, store, obs)
        first = _reserve_close(conn, store, observation_id)
        second = reserve_runtime_flatten(
            conn,
            store,
            order_intent_id="intent-runtime-close-retry",
            trade_id="trade-runtime-close",
            idempotency_key="idem-runtime-close",
            exit_reason=ExitReason.STRUCTURE,
            market_observation_id=observation_id,
            created_at_utc=T0 + timedelta(seconds=2),
            event_id="evt-runtime-close-reserve-retry",
        )
        close_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["order_intents"]
            ).where(store.tables["order_intents"].c.intent_kind == "CLOSE")
        ).scalar_one()

    assert first["state"] == "RESERVED"
    assert second["duplicate"] is True
    assert second["order_intent_id"] == "intent-runtime-close"
    assert close_count == 1


def test_runtime_close_reserve_requires_matching_flatten_request() -> None:
    engine, store, obs = _fixture()
    with engine.begin() as conn:
        assert _reserve(conn, store, obs)["state"] == "RESERVED"
        assert submit_runtime_reserved_open(
            conn,
            store,
            order_intent_id="intent-runtime-portfolio",
            submitted_at_utc=T0,
            event_id="evt-runtime-close-no-request-submit",
        )["state"] == "SUBMITTED"
        fill_at = T0 + timedelta(milliseconds=250)
        fill_obs = replace(
            obs,
            observation_id="obs-runtime-close-no-request",
            exchange_ts=fill_at,
            received_ts=fill_at,
        )
        store.record_market_observation(conn, fill_obs)
        assert fill_runtime_submitted_open(
            conn,
            store,
            order_intent_id="intent-runtime-portfolio",
            trade_id="trade-runtime-close",
            fill_market_observation_id=fill_obs.observation_id,
            filled_at_utc=fill_at,
            event_id="evt-runtime-close-no-request-open",
        )["state"] == "FILLED"

        with pytest.raises(RuntimeError, match="FLATTEN_REQUEST"):
            reserve_runtime_flatten(
                conn,
                store,
                order_intent_id="intent-runtime-close",
                trade_id="trade-runtime-close",
                idempotency_key="idem-runtime-close",
                exit_reason=ExitReason.STRUCTURE,
                market_observation_id=fill_obs.observation_id,
                created_at_utc=T0 + timedelta(seconds=1),
                event_id="evt-runtime-close-no-request-reserve",
            )
        close_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["order_intents"]
            ).where(store.tables["order_intents"].c.intent_kind == "CLOSE")
        ).scalar_one()

    assert close_count == 0
