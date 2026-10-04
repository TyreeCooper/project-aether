from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
import sqlalchemy as sa

from aether_vnext.exit_plan import ExitReason
from aether_vnext.runtime_execution_bridge import submit_runtime_reserved_open
from aether_vnext.runtime_exit_request_bridge import request_runtime_flatten
from aether_vnext.runtime_fill_bridge import fill_runtime_submitted_open
from tests_vnext.test_runtime_portfolio_bridge import T0, _fixture, _reserve


def _open(conn, store, obs) -> str:
    assert _reserve(conn, store, obs)["state"] == "RESERVED"
    assert submit_runtime_reserved_open(
        conn,
        store,
        order_intent_id="intent-runtime-portfolio",
        submitted_at_utc=T0,
        event_id="evt-runtime-exit-submit",
    )["state"] == "SUBMITTED"

    fill_at = T0 + timedelta(milliseconds=250)
    fill_obs = replace(
        obs,
        observation_id="obs-runtime-exit-open",
        exchange_ts=fill_at,
        received_ts=fill_at,
    )
    store.record_market_observation(conn, fill_obs)
    result = fill_runtime_submitted_open(
        conn,
        store,
        order_intent_id="intent-runtime-portfolio",
        trade_id="trade-runtime-exit",
        fill_market_observation_id=fill_obs.observation_id,
        filled_at_utc=fill_at,
        event_id="evt-runtime-exit-open",
    )
    assert result["state"] == "FILLED"
    return fill_obs.observation_id


def test_runtime_exit_request_records_flatten_without_touching_open_book() -> None:
    engine, store, obs = _fixture()
    with engine.begin() as conn:
        observation_id = _open(conn, store, obs)
        result = request_runtime_flatten(
            conn,
            store,
            trade_id="trade-runtime-exit",
            exit_reason=ExitReason.STRUCTURE,
            market_observation_id=observation_id,
            at_utc=T0 + timedelta(seconds=1),
            event_id="evt-runtime-exit-request",
        )
        open_trade_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["open_trades"]
            )
        ).scalar_one()
        active_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["active_positions"]
            )
        ).scalar_one()
        close_intent_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["order_intents"]
            ).where(store.tables["order_intents"].c.intent_kind == "CLOSE")
        ).scalar_one()
        event = conn.execute(
            sa.select(store.tables["event_ledger"]).where(
                store.tables["event_ledger"].c.event_id
                == "evt-runtime-exit-request"
            )
        ).mappings().one()
        ledger = conn.execute(
            sa.select(store.tables["broker_account_ledgers"]).where(
                store.tables["broker_account_ledgers"].c.broker_account_id
                == "kraken_paper"
            )
        ).mappings().one()

    assert result["ok"] is True
    assert result["state"] == "FLATTEN_REQUEST"
    assert open_trade_count == 1
    assert active_count == 1
    assert close_intent_count == 0
    assert event["reason_code"] == "structure"
    assert event["prior_state"] == "OPEN"
    assert event["new_state"] == "FLATTEN_REQUEST"
    assert ledger["cash_reserved_usd"] > 0


def test_runtime_exit_request_rejects_non_trigger_plan_complete() -> None:
    engine, store, obs = _fixture()
    with engine.begin() as conn:
        observation_id = _open(conn, store, obs)
        with pytest.raises(
            ValueError,
            match="not an active EXIT_PRECEDENCE trigger",
        ):
            request_runtime_flatten(
                conn,
                store,
                trade_id="trade-runtime-exit",
                exit_reason=ExitReason.PLAN_COMPLETE,
                market_observation_id=observation_id,
                at_utc=T0 + timedelta(seconds=1),
                event_id="evt-runtime-exit-plan-complete",
            )


def test_runtime_exit_request_rejects_wrong_asset_observation() -> None:
    engine, store, obs = _fixture()
    with engine.begin() as conn:
        _open(conn, store, obs)
        wrong = replace(
            obs,
            observation_id="obs-runtime-exit-wrong-asset",
            asset_id="eth",
        )
        store.record_market_observation(conn, wrong)
        with pytest.raises(ValueError, match="asset mismatch"):
            request_runtime_flatten(
                conn,
                store,
                trade_id="trade-runtime-exit",
                exit_reason=ExitReason.STRUCTURE,
                market_observation_id=wrong.observation_id,
                at_utc=T0 + timedelta(seconds=1),
                event_id="evt-runtime-exit-wrong-asset",
            )
