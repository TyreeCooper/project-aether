from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
import sqlalchemy as sa

from aether_vnext.exit_plan import ExitReason
from aether_vnext.restart import load_restart_snapshot
from aether_vnext.runtime_close_execution_bridge import (
    submit_runtime_reserved_close,
)
from aether_vnext.runtime_close_fill_bridge import fill_runtime_submitted_close
from aether_vnext.runtime_close_reserve_bridge import reserve_runtime_flatten
from aether_vnext.runtime_execution_bridge import submit_runtime_reserved_open
from aether_vnext.runtime_exit_request_bridge import request_runtime_flatten
from aether_vnext.runtime_fill_bridge import fill_runtime_submitted_open
from aether_vnext.runtime_portfolio_bridge import reserve_runtime_ready_ticket
from tests_vnext.test_runtime_portfolio_bridge import T0, _fixture


def _ids(rows: tuple[dict, ...], field: str) -> tuple[str, ...]:
    return tuple(str(row[field]) for row in rows)


def test_runtime_restart_snapshots_preserve_recovery_and_idempotency() -> None:
    engine, store, obs = _fixture()

    open_intent_id = "intent-runtime-restart-open"
    trade_id = "trade-runtime-restart"
    close_intent_id = "intent-runtime-restart-close"
    close_key = "idem-runtime-restart-close"

    open_fill_at = T0 + timedelta(milliseconds=250)
    close_fill_at = T0 + timedelta(seconds=2, milliseconds=250)
    open_fill_obs = replace(
        obs,
        observation_id="obs-runtime-restart-open-fill",
        exchange_ts=open_fill_at,
        received_ts=open_fill_at,
        age_ms=0,
    )
    close_fill_obs = replace(
        obs,
        observation_id="obs-runtime-restart-close-fill",
        bid=101_000.0,
        ask=101_020.0,
        last=101_010.0,
        mark=101_010.0,
        spread_abs=20.0,
        spread_bps=(20.0 / 101_010.0) * 10_000.0,
        exchange_ts=close_fill_at,
        received_ts=close_fill_at,
        age_ms=0,
    )

    with engine.begin() as conn:
        reserved = reserve_runtime_ready_ticket(
            conn,
            store,
            ticket_id="ticket-runtime-portfolio",
            order_intent_id=open_intent_id,
            current_observation=obs,
            current_observations={"btc": obs},
            created_at_utc=T0,
            event_id="evt-runtime-restart-open-reserve",
        )
        assert reserved["state"] == "RESERVED"

        restart_reserved = load_restart_snapshot(conn, store=store)
        assert _ids(
            restart_reserved.in_flight_order_intents,
            "order_intent_id",
        ) == (open_intent_id,)
        assert _ids(
            restart_reserved.risk_admission_reservations,
            "order_intent_id",
        ) == (open_intent_id,)
        assert restart_reserved.risk_admission_issues == ()

        retry_reserve = reserve_runtime_ready_ticket(
            conn,
            store,
            ticket_id="ticket-runtime-portfolio",
            order_intent_id="intent-runtime-restart-open-retry",
            current_observation=obs,
            current_observations={"btc": obs},
            created_at_utc=T0,
            event_id="evt-runtime-restart-open-reserve-retry",
        )
        assert retry_reserve["duplicate"] is True
        assert retry_reserve["order_intent_id"] == open_intent_id

        submitted = submit_runtime_reserved_open(
            conn,
            store,
            order_intent_id=open_intent_id,
            submitted_at_utc=T0,
            event_id="evt-runtime-restart-open-submit",
        )
        assert submitted["state"] == "SUBMITTED"

        restart_submitted = load_restart_snapshot(conn, store=store)
        assert _ids(
            restart_submitted.in_flight_order_intents,
            "order_intent_id",
        ) == (open_intent_id,)
        assert restart_submitted.risk_admission_issues == ()

        retry_submit = submit_runtime_reserved_open(
            conn,
            store,
            order_intent_id=open_intent_id,
            submitted_at_utc=T0 + timedelta(milliseconds=50),
            event_id="evt-runtime-restart-open-submit-retry",
        )
        assert retry_submit["duplicate"] is True

        store.record_market_observation(conn, open_fill_obs)
        opened = fill_runtime_submitted_open(
            conn,
            store,
            order_intent_id=open_intent_id,
            trade_id=trade_id,
            fill_market_observation_id=open_fill_obs.observation_id,
            filled_at_utc=open_fill_at,
            event_id="evt-runtime-restart-open-fill",
        )
        assert opened["state"] == "FILLED"

        restart_open = load_restart_snapshot(conn, store=store)
        assert restart_open.in_flight_order_intents == ()
        assert _ids(restart_open.active_positions, "trade_id") == (trade_id,)
        assert _ids(restart_open.open_trade_records, "trade_id") == (trade_id,)
        assert _ids(
            restart_open.consumed_signals,
            "trade_id",
        ) == (trade_id,)
        assert restart_open.risk_admission_reservations == ()
        assert restart_open.risk_admission_issues == ()

        requested = request_runtime_flatten(
            conn,
            store,
            trade_id=trade_id,
            exit_reason=ExitReason.STRUCTURE,
            market_observation_id=open_fill_obs.observation_id,
            at_utc=T0 + timedelta(seconds=1),
            event_id="evt-runtime-restart-flatten-request",
        )
        assert requested["state"] == "FLATTEN_REQUEST"

        close_reserved = reserve_runtime_flatten(
            conn,
            store,
            order_intent_id=close_intent_id,
            trade_id=trade_id,
            idempotency_key=close_key,
            exit_reason=ExitReason.STRUCTURE,
            market_observation_id=open_fill_obs.observation_id,
            created_at_utc=T0 + timedelta(seconds=1),
            event_id="evt-runtime-restart-close-reserve",
        )
        assert close_reserved["state"] == "RESERVED"

        close_submitted = submit_runtime_reserved_close(
            conn,
            store,
            order_intent_id=close_intent_id,
            submitted_at_utc=T0 + timedelta(seconds=2),
            event_id="evt-runtime-restart-close-submit",
        )
        assert close_submitted["state"] == "SUBMITTED"

        restart_close_submitted = load_restart_snapshot(conn, store=store)
        assert _ids(
            restart_close_submitted.in_flight_order_intents,
            "order_intent_id",
        ) == (close_intent_id,)
        assert _ids(
            restart_close_submitted.active_positions,
            "trade_id",
        ) == (trade_id,)
        assert restart_close_submitted.risk_admission_issues == ()

        close_submit_retry = submit_runtime_reserved_close(
            conn,
            store,
            order_intent_id=close_intent_id,
            submitted_at_utc=T0 + timedelta(seconds=2, milliseconds=50),
            event_id="evt-runtime-restart-close-submit-retry",
        )
        assert close_submit_retry["duplicate"] is True

        store.record_market_observation(conn, close_fill_obs)
        flat = fill_runtime_submitted_close(
            conn,
            store,
            order_intent_id=close_intent_id,
            fill_market_observation_id=close_fill_obs.observation_id,
            filled_at_utc=close_fill_at,
            event_id="evt-runtime-restart-close-fill",
        )
        assert flat["state"] == "FLAT"

        final_first = load_restart_snapshot(conn, store=store)
        final_second = load_restart_snapshot(conn, store=store)

        assert final_first.in_flight_order_intents == ()
        assert final_first.active_positions == ()
        assert _ids(final_first.open_trade_records, "trade_id") == (trade_id,)
        assert _ids(final_first.consumed_signals, "trade_id") == (trade_id,)
        assert final_first.risk_admission_reservations == ()
        assert final_first.risk_admission_issues == ()
        assert final_second.event_count == final_first.event_count

        closed_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["closed_trades"]
            ).where(store.tables["closed_trades"].c.trade_id == trade_id)
        ).scalar_one()
        assert closed_count == 1

        ledger = conn.execute(
            sa.select(store.tables["broker_account_ledgers"]).where(
                store.tables["broker_account_ledgers"].c.broker_account_id
                == "kraken_paper"
            )
        ).mappings().one()
        assert ledger["cash_reserved_usd"] == pytest.approx(0.0)
        assert ledger["margin_used_usd"] == pytest.approx(0.0)
