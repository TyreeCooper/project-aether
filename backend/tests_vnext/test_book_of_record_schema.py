from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from aether_vnext.store import (
    SEED_LEDGER_CASH_USD,
    VNextStore,
    canonical_payload_hash,
)


UTC = timezone.utc
NOW = datetime(2026, 9, 26, 4, 15, tzinfo=UTC)


def _engine_and_store():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
    return engine, store


def test_book_of_record_has_required_tables() -> None:
    _, store = _engine_and_store()
    assert {
        "product_registry_state",
        "market_observations",
        "policy_snapshots",
        "governor_state",
        "broker_account_ledgers",
        "setups",
        "tickets",
        "exit_plans",
        "order_intents",
        "open_trades",
        "active_positions",
        "closed_trades",
        "review_cards",
        "signal_consumptions",
        "mutation_idempotency",
        "ledger_transfers",
        "reconciliation_runs",
        "event_ledger",
    } <= set(store.tables)


def test_seed_ledgers_total_10k_and_restart_never_reseeds() -> None:
    engine, store = _engine_and_store()
    assert sum(SEED_LEDGER_CASH_USD.values()) == 10_000.0

    with engine.begin() as conn:
        assert store.provision_seed_ledgers_once(conn) is True

    with engine.begin() as conn:
        ledgers = store.tables["broker_account_ledgers"]
        conn.execute(
            ledgers.update()
            .where(ledgers.c.broker_account_id == "kraken_paper")
            .values(cash_available_usd=3500.0)
        )

    with engine.begin() as conn:
        assert store.provision_seed_ledgers_once(conn) is False
        rows = {
            row["broker_account_id"]: row
            for row in store.ledger_rows(conn)
        }
        assert rows["kraken_paper"]["cash_available_usd"] == 3500.0
        assert rows["tastyfx_paper"]["cash_available_usd"] == 2000.0
        assert rows["ninja_paper"]["cash_available_usd"] == 2000.0
        assert rows["ibkr_paper"]["cash_available_usd"] == 2000.0


def test_event_payload_hash_is_canonical() -> None:
    a = canonical_payload_hash({"b": 2, "a": 1})
    b = canonical_payload_hash({"a": 1, "b": 2})
    assert a == b
    assert len(a) == 64


def test_event_ids_are_durable_and_unique() -> None:
    engine, store = _engine_and_store()
    kwargs = dict(
        event_id="evt-1",
        aggregate_type="setup",
        aggregate_id="setup-1",
        prior_state=None,
        new_state="WATCH",
        seat="Scout",
        reason_code="no_setup",
        policy_version="AETHER-POLICY-TEST",
        configuration_hash="cfg",
        market_observation_id=None,
        actor="test",
        created_at_utc=NOW,
        payload={"x": 1},
    )
    with engine.begin() as conn:
        store.append_event(conn, **kwargs)
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            store.append_event(conn, **kwargs)


def test_signal_ticket_and_idempotency_constraints_exist() -> None:
    _, store = _engine_and_store()

    tickets = store.tables["tickets"]
    order_intents = store.tables["order_intents"]
    signal_consumptions = store.tables["signal_consumptions"]
    active_positions = store.tables["active_positions"]
    mutations = store.tables["mutation_idempotency"]

    ticket_unique = {
        tuple(constraint.columns.keys())
        for constraint in tickets.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }
    intent_unique = {
        tuple(constraint.columns.keys())
        for constraint in order_intents.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }

    assert ("signal_key",) in ticket_unique
    assert ("idempotency_key",) in intent_unique
    assert tuple(signal_consumptions.primary_key.columns.keys()) == ("signal_key",)
    assert tuple(active_positions.primary_key.columns.keys()) == ("position_key",)
    assert tuple(mutations.primary_key.columns.keys()) == ("idempotency_key",)


def test_lineage_foreign_key_chain_is_present() -> None:
    _, store = _engine_and_store()

    def targets(table_name: str) -> set[str]:
        table = store.tables[table_name]
        return {
            fk.target_fullname
            for constraint in table.foreign_key_constraints
            for fk in constraint.elements
        }

    assert "setups.setup_id" in targets("tickets")
    assert "tickets.ticket_id" in targets("order_intents")
    assert "order_intents.order_intent_id" in targets("open_trades")
    assert "open_trades.trade_id" in targets("closed_trades")
    assert "closed_trades.trade_id" in targets("review_cards")


def test_one_active_position_per_position_key_is_database_enforced() -> None:
    _, store = _engine_and_store()
    active = store.tables["active_positions"]
    assert tuple(active.primary_key.columns.keys()) == ("position_key",)
    unique_sets = {
        tuple(c.columns.keys())
        for c in active.constraints
        if isinstance(c, sa.UniqueConstraint)
    }
    assert ("trade_id",) in unique_sets


def test_broker_ledger_and_governor_have_optimistic_row_versions() -> None:
    _, store = _engine_and_store()
    assert "row_version" in store.tables["broker_account_ledgers"].c
    assert "row_version" in store.tables["governor_state"].c


def test_phase3_migration_seeds_once_and_makes_event_ledger_append_only() -> None:
    backend = Path(__file__).resolve().parents[1]
    migration = (
        backend
        / "alembic"
        / "versions"
        / "0003_aether_vnext_book_of_record.py"
    ).read_text(encoding="utf-8")

    assert "ON CONFLICT (broker_account_id) DO NOTHING" in migration
    assert "('kraken_paper', 4000" in migration
    assert "('tastyfx_paper', 2000" in migration
    assert "('ninja_paper', 2000" in migration
    assert "('ibkr_paper', 2000" in migration
    assert "reject_event_ledger_mutation" in migration
    assert "BEFORE UPDATE OR DELETE" in migration


def test_vnext_schema_does_not_name_legacy_runtime_state_table() -> None:
    _, store = _engine_and_store()
    assert "aether_runtime_state" not in store.tables
