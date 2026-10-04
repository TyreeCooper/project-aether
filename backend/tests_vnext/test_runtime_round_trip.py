from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
import sqlalchemy as sa

from aether_vnext.exit_plan import ExitReason
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


def _ledger(conn, store):
    return conn.execute(
        sa.select(store.tables["broker_account_ledgers"]).where(
            store.tables["broker_account_ledgers"].c.broker_account_id
            == "kraken_paper"
        )
    ).mappings().one()


def _count(conn, table) -> int:
    return int(
        conn.execute(
            sa.select(sa.func.count()).select_from(table)
        ).scalar_one()
    )


def test_runtime_round_trip_preserves_lineage_idempotency_risk_and_accounting() -> None:
    engine, store, obs = _fixture()

    open_intent_id = "intent-runtime-round-trip-open"
    trade_id = "trade-runtime-round-trip"
    close_intent_id = "intent-runtime-round-trip-close"
    close_idempotency_key = "idem-runtime-round-trip-close"

    open_fill_at = T0 + timedelta(milliseconds=250)
    close_fill_at = T0 + timedelta(seconds=2, milliseconds=250)

    open_fill_obs = replace(
        obs,
        observation_id="obs-runtime-round-trip-open-fill",
        exchange_ts=open_fill_at,
        received_ts=open_fill_at,
        age_ms=0,
    )
    close_fill_obs = replace(
        obs,
        observation_id="obs-runtime-round-trip-close-fill",
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
        starting = _ledger(conn, store)

        reserved_open = reserve_runtime_ready_ticket(
            conn,
            store,
            ticket_id="ticket-runtime-portfolio",
            order_intent_id=open_intent_id,
            current_observation=obs,
            current_observations={"btc": obs},
            created_at_utc=T0,
            event_id="evt-runtime-round-trip-open-reserve",
        )
        assert reserved_open["state"] == "RESERVED"
        assert _count(conn, store.tables["risk_admission_reservations"]) == 1

        duplicate_open = reserve_runtime_ready_ticket(
            conn,
            store,
            ticket_id="ticket-runtime-portfolio",
            order_intent_id="intent-runtime-round-trip-open-retry",
            current_observation=obs,
            current_observations={"btc": obs},
            created_at_utc=T0,
            event_id="evt-runtime-round-trip-open-reserve-retry",
        )
        assert duplicate_open["duplicate"] is True
        assert duplicate_open["order_intent_id"] == open_intent_id
        assert _count(conn, store.tables["order_intents"]) == 1

        reserved_ledger = _ledger(conn, store)
        assert reserved_ledger["cash_reserved_usd"] > 0
        assert reserved_ledger["cash_available_usd"] < starting["cash_available_usd"]

        submitted_open = submit_runtime_reserved_open(
            conn,
            store,
            order_intent_id=open_intent_id,
            submitted_at_utc=T0,
            event_id="evt-runtime-round-trip-open-submit",
        )
        assert submitted_open["state"] == "SUBMITTED"

        store.record_market_observation(conn, open_fill_obs)
        filled_open = fill_runtime_submitted_open(
            conn,
            store,
            order_intent_id=open_intent_id,
            trade_id=trade_id,
            fill_market_observation_id=open_fill_obs.observation_id,
            filled_at_utc=open_fill_at,
            event_id="evt-runtime-round-trip-open-fill",
        )
        assert filled_open["state"] == "FILLED"
        assert filled_open["trade_id"] == trade_id
        assert _count(conn, store.tables["risk_admission_reservations"]) == 0
        assert _count(conn, store.tables["active_positions"]) == 1
        assert _count(conn, store.tables["signal_consumptions"]) == 1

        lineage_after_open = conn.execute(
            sa.select(store.tables["decision_lineage"]).where(
                store.tables["decision_lineage"].c.firm_event_id
                == "firm-runtime-portfolio"
            )
        ).mappings().one()
        assert lineage_after_open["order_intent_id"] == open_intent_id
        assert lineage_after_open["trade_id"] == trade_id
        assert lineage_after_open["ticket_id"] == "ticket-runtime-portfolio"

        flatten = request_runtime_flatten(
            conn,
            store,
            trade_id=trade_id,
            exit_reason=ExitReason.STRUCTURE,
            market_observation_id=open_fill_obs.observation_id,
            at_utc=T0 + timedelta(seconds=1),
            event_id="evt-runtime-round-trip-flatten-request",
        )
        assert flatten["state"] == "FLATTEN_REQUEST"

        reserved_close = reserve_runtime_flatten(
            conn,
            store,
            order_intent_id=close_intent_id,
            trade_id=trade_id,
            idempotency_key=close_idempotency_key,
            exit_reason=ExitReason.STRUCTURE,
            market_observation_id=open_fill_obs.observation_id,
            created_at_utc=T0 + timedelta(seconds=1),
            event_id="evt-runtime-round-trip-close-reserve",
        )
        assert reserved_close["state"] == "RESERVED"

        duplicate_close = reserve_runtime_flatten(
            conn,
            store,
            order_intent_id="intent-runtime-round-trip-close-retry",
            trade_id=trade_id,
            idempotency_key=close_idempotency_key,
            exit_reason=ExitReason.STRUCTURE,
            market_observation_id=open_fill_obs.observation_id,
            created_at_utc=T0 + timedelta(seconds=1, milliseconds=100),
            event_id="evt-runtime-round-trip-close-reserve-retry",
        )
        assert duplicate_close["duplicate"] is True
        assert duplicate_close["order_intent_id"] == close_intent_id

        close_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["order_intents"]
            ).where(store.tables["order_intents"].c.intent_kind == "CLOSE")
        ).scalar_one()
        assert close_count == 1

        submitted_close = submit_runtime_reserved_close(
            conn,
            store,
            order_intent_id=close_intent_id,
            submitted_at_utc=T0 + timedelta(seconds=2),
            event_id="evt-runtime-round-trip-close-submit",
        )
        assert submitted_close["state"] == "SUBMITTED"

        store.record_market_observation(conn, close_fill_obs)
        flat = fill_runtime_submitted_close(
            conn,
            store,
            order_intent_id=close_intent_id,
            fill_market_observation_id=close_fill_obs.observation_id,
            filled_at_utc=close_fill_at,
            event_id="evt-runtime-round-trip-close-fill",
        )
        assert flat["state"] == "FLAT"
        assert flat["trade_id"] == trade_id

        duplicate_flat = fill_runtime_submitted_close(
            conn,
            store,
            order_intent_id=close_intent_id,
            fill_market_observation_id=close_fill_obs.observation_id,
            filled_at_utc=close_fill_at + timedelta(seconds=1),
            event_id="evt-runtime-round-trip-close-fill-retry",
        )
        assert duplicate_flat["duplicate"] is True
        assert duplicate_flat["trade_id"] == trade_id

        closed = conn.execute(
            sa.select(store.tables["closed_trades"]).where(
                store.tables["closed_trades"].c.trade_id == trade_id
            )
        ).mappings().one()
        final_ledger = _ledger(conn, store)
        final_lineage = conn.execute(
            sa.select(store.tables["decision_lineage"]).where(
                store.tables["decision_lineage"].c.firm_event_id
                == "firm-runtime-portfolio"
            )
        ).mappings().one()

        assert _count(conn, store.tables["active_positions"]) == 0
        assert _count(conn, store.tables["closed_trades"]) == 1
        assert _count(conn, store.tables["open_trades"]) == 1
        assert _count(conn, store.tables["signal_consumptions"]) == 1
        assert _count(conn, store.tables["risk_admission_reservations"]) == 0

        assert closed["exit_reason"] == "structure"
        assert closed["duration_s"] > 0
        assert closed["fees_usd"] > 0
        assert closed["total_cost_usd"] >= closed["fees_usd"]

        assert final_ledger["cash_reserved_usd"] == pytest.approx(0.0)
        assert final_ledger["margin_used_usd"] == pytest.approx(0.0)
        assert final_ledger["realized_pnl_usd"] == pytest.approx(
            closed["net_pnl_usd"]
        )
        assert final_ledger["cash_available_usd"] == pytest.approx(
            float(starting["cash_available_usd"]) + float(closed["net_pnl_usd"])
        )

        assert final_lineage["setup_id"] == "setup-runtime-portfolio"
        assert final_lineage["ticket_id"] == "ticket-runtime-portfolio"
        assert final_lineage["order_intent_id"] == open_intent_id
        assert final_lineage["trade_id"] == trade_id
        assert (
            final_lineage["market_observation_id"]
            == close_fill_obs.observation_id
        )
