from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa

from aether_vnext.restart import load_restart_snapshot
from aether_vnext.store import VNextStore


UTC = timezone.utc
NOW = datetime(2026, 9, 26, 4, 25, tzinfo=UTC)


def test_restart_snapshot_is_read_only_and_does_not_reseed_ledgers() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)

    with engine.begin() as conn:
        store.create_all_for_test(conn)
        assert store.provision_seed_ledgers_once(conn) is True

        ledgers = store.tables["broker_account_ledgers"]
        conn.execute(
            ledgers.update()
            .where(ledgers.c.broker_account_id == "kraken_paper")
            .values(
                cash_available_usd=3123.45,
                realized_pnl_usd=-76.55,
                row_version=2,
            )
        )

        store.append_event(
            conn,
            event_id="evt-restart-1",
            aggregate_type="ledger",
            aggregate_id="kraken_paper",
            prior_state="seed",
            new_state="marked",
            seat="Portfolio",
            reason_code="plan_complete",
            policy_version="policy-test",
            configuration_hash="cfg-test",
            market_observation_id=None,
            actor="test",
            created_at_utc=NOW,
            payload={"cash_available_usd": 3123.45},
        )

    with engine.begin() as conn:
        first = load_restart_snapshot(conn, store=store)
        second = load_restart_snapshot(conn, store=store)

    first_ledgers = {
        row["broker_account_id"]: row
        for row in first.broker_ledgers
    }
    second_ledgers = {
        row["broker_account_id"]: row
        for row in second.broker_ledgers
    }

    assert first_ledgers["kraken_paper"]["cash_available_usd"] == 3123.45
    assert second_ledgers["kraken_paper"]["cash_available_usd"] == 3123.45
    assert first_ledgers["kraken_paper"]["row_version"] == 2
    assert second_ledgers["kraken_paper"]["row_version"] == 2
    assert first.event_count == 1
    assert second.event_count == 1

    # A restart read never invokes provisioning. Even an explicit provisioning
    # attempt after restart is a no-op because persisted ledgers already exist.
    with engine.begin() as conn:
        assert store.provision_seed_ledgers_once(conn) is False
        rows = {
            row["broker_account_id"]: row
            for row in store.ledger_rows(conn)
        }
        assert rows["kraken_paper"]["cash_available_usd"] == 3123.45


def test_restart_snapshot_does_not_promote_terminal_records_to_inflight() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)

    with engine.begin() as conn:
        store.create_all_for_test(conn)
        assert store.provision_seed_ledgers_once(conn) is True

    with engine.begin() as conn:
        snapshot = load_restart_snapshot(conn, store=store)

    assert snapshot.in_flight_setups == ()
    assert snapshot.in_flight_tickets == ()
    assert snapshot.in_flight_order_intents == ()
    assert len(snapshot.broker_ledgers) == 4
