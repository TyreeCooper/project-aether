from __future__ import annotations

from datetime import timedelta

import pytest
import sqlalchemy as sa

from aether_vnext.exit_plan import ExitReason
from aether_vnext.runtime_close_execution_bridge import submit_runtime_reserved_close
from aether_vnext.runtime_close_reserve_bridge import reserve_runtime_flatten
from tests_vnext.test_runtime_close_reserve_bridge import _open_and_request
from tests_vnext.test_runtime_portfolio_bridge import T0, _fixture


def _reserve_close(conn, store, obs) -> None:
    observation_id = _open_and_request(conn, store, obs)
    result = reserve_runtime_flatten(
        conn,
        store,
        order_intent_id="intent-runtime-close",
        trade_id="trade-runtime-close",
        idempotency_key="idem-runtime-close",
        exit_reason=ExitReason.STRUCTURE,
        market_observation_id=observation_id,
        created_at_utc=T0 + timedelta(seconds=1),
        event_id="evt-runtime-close-execution-reserve",
    )
    assert result["state"] == "RESERVED"


def test_runtime_close_submit_advances_reserved_close_without_releasing_open_book() -> None:
    engine, store, obs = _fixture()
    with engine.begin() as conn:
        _reserve_close(conn, store, obs)
        before = conn.execute(
            sa.select(store.tables["broker_account_ledgers"]).where(
                store.tables["broker_account_ledgers"].c.broker_account_id
                == "kraken_paper"
            )
        ).mappings().one()

        result = submit_runtime_reserved_close(
            conn,
            store,
            order_intent_id="intent-runtime-close",
            submitted_at_utc=T0 + timedelta(seconds=2),
            event_id="evt-runtime-close-execution-submit",
        )
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
        open_count = conn.execute(
            sa.select(sa.func.count()).select_from(
                store.tables["open_trades"]
            )
        ).scalar_one()

    assert result["ok"] is True
    assert result["state"] == "SUBMITTED"
    assert close_intent is not None
    assert close_intent.state.value == "SUBMITTED"
    assert close_intent.filled_at is None
    assert close_intent.filled_qty == pytest.approx(0.0)
    assert close_intent.reserved_cash_usd == pytest.approx(0.0)
    assert close_intent.reserved_margin_usd == pytest.approx(0.0)
    assert after["cash_reserved_usd"] == pytest.approx(before["cash_reserved_usd"])
    assert after["margin_used_usd"] == pytest.approx(before["margin_used_usd"])
    assert active_count == 1
    assert open_count == 1


def test_runtime_close_submit_retry_is_idempotent() -> None:
    engine, store, obs = _fixture()
    with engine.begin() as conn:
        _reserve_close(conn, store, obs)
        first = submit_runtime_reserved_close(
            conn,
            store,
            order_intent_id="intent-runtime-close",
            submitted_at_utc=T0 + timedelta(seconds=2),
            event_id="evt-runtime-close-execution-submit",
        )
        second = submit_runtime_reserved_close(
            conn,
            store,
            order_intent_id="intent-runtime-close",
            submitted_at_utc=T0 + timedelta(seconds=3),
            event_id="evt-runtime-close-execution-submit-retry",
        )

    assert first["state"] == "SUBMITTED"
    assert second == {
        "ok": True,
        "duplicate": True,
        "state": "SUBMITTED",
    }


def test_runtime_close_submit_refuses_missing_active_position() -> None:
    engine, store, obs = _fixture()
    with engine.begin() as conn:
        _reserve_close(conn, store, obs)
        conn.execute(store.tables["active_positions"].delete())
        with pytest.raises(RuntimeError, match="active position"):
            submit_runtime_reserved_close(
                conn,
                store,
                order_intent_id="intent-runtime-close",
                submitted_at_utc=T0 + timedelta(seconds=2),
                event_id="evt-runtime-close-execution-no-position",
            )
        close_intent = store.load_order_intent(
            conn,
            order_intent_id="intent-runtime-close",
        )

    assert close_intent is not None
    assert close_intent.state.value == "RESERVED"
