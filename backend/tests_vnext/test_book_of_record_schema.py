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
        "decision_lineage",
        "setups",
        "tickets",
        "exit_plans",
        "order_intents",
        "open_trades",
        "active_positions",
        "closed_trades",
        "review_cards",
        "route_review_state",
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

    assert "decision_lineage.firm_event_id" in targets("setups")
    assert "setups.setup_id" in targets("tickets")
    assert "decision_lineage.firm_event_id" in targets("tickets")
    assert "tickets.ticket_id" in targets("order_intents")
    assert "decision_lineage.firm_event_id" in targets("order_intents")
    assert "order_intents.order_intent_id" in targets("open_trades")
    assert "decision_lineage.firm_event_id" in targets("open_trades")
    assert "open_trades.trade_id" in targets("closed_trades")
    assert "decision_lineage.firm_event_id" in targets("closed_trades")
    assert "closed_trades.trade_id" in targets("review_cards")
    assert "decision_lineage.firm_event_id" in targets("review_cards")
    assert "review_cards.review_card_id" in targets("route_review_state")


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
    assert "reject_immutable_mutation" in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "trg_event_ledger_append_only" in migration
    assert "trg_policy_snapshots_immutable" in migration
    assert "trg_exit_plans_immutable" in migration
    assert "trg_closed_trades_immutable" in migration
    assert "trg_signal_consumptions_immutable" in migration
    assert "AS $aether$" in migration
    assert "$aether$;" in migration
    assert "schema_v0003" in migration


def test_vnext_schema_does_not_name_legacy_runtime_state_table() -> None:
    _, store = _engine_and_store()
    assert "aether_runtime_state" not in store.tables


def test_mutation_idempotency_key_cannot_be_recorded_twice() -> None:
    engine, store = _engine_and_store()
    with engine.begin() as conn:
        store.record_mutation_idempotency(
            conn,
            idempotency_key="idem-1",
            mutation_type="reserve",
            aggregate_type="order_intent",
            aggregate_id="oi-1",
            created_at_utc=NOW,
        )
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            store.record_mutation_idempotency(
                conn,
                idempotency_key="idem-1",
                mutation_type="reserve",
                aggregate_type="order_intent",
                aggregate_id="oi-1",
                created_at_utc=NOW,
            )


def test_active_position_key_cannot_be_claimed_twice() -> None:
    engine, store = _engine_and_store()
    with engine.begin() as conn:
        store.claim_active_position(
            conn,
            position_key="btc:daily_swing",
            trade_id="trade-1",
            asset_id="btc",
            horizon="daily_swing",
            side="long",
            quantity=0.01,
            updated_at_utc=NOW,
        )
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            store.claim_active_position(
                conn,
                position_key="btc:daily_swing",
                trade_id="trade-2",
                asset_id="btc",
                horizon="daily_swing",
                side="long",
                quantity=0.02,
                updated_at_utc=NOW,
            )


def test_signal_consumption_is_database_unique() -> None:
    engine, store = _engine_and_store()
    with engine.begin() as conn:
        store.consume_signal(
            conn,
            signal_key="signal-1",
            order_intent_id="oi-1",
            trade_id="trade-1",
            consumed_at_utc=NOW,
        )
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            store.consume_signal(
                conn,
                signal_key="signal-1",
                order_intent_id="oi-2",
                trade_id="trade-2",
                consumed_at_utc=NOW,
            )


def test_decision_lineage_contains_universal_forensic_fields() -> None:
    _, store = _engine_and_store()
    lineage = store.tables["decision_lineage"]
    assert {
        "firm_event_id",
        "setup_id",
        "ticket_id",
        "order_intent_id",
        "trade_id",
        "asset_id",
        "route_id",
        "policy_version",
        "configuration_hash",
        "market_observation_id",
        "first_killed_by",
        "first_kill_reason",
        "created_at_utc",
        "row_version",
    } <= set(lineage.c.keys())


def test_route_review_projection_preserves_bench_or_keep_across_restart() -> None:
    _, store = _engine_and_store()
    route_state = store.tables["route_review_state"]
    assert tuple(route_state.primary_key.columns.keys()) == ("route_id",)
    assert {"evidence_state", "operational_state", "review_card_id", "row_version"} <= set(
        route_state.c.keys()
    )


def test_phase5_execution_reservation_columns_are_in_current_schema() -> None:
    _, store = _engine_and_store()
    columns = set(store.tables["order_intents"].c.keys())
    assert {
        "broker_account_id",
        "exit_plan_id",
        "intent_kind",
        "position_key",
        "signal_key",
        "reserved_cash_usd",
        "reserved_margin_usd",
        "ready_spread_bps",
        "hard_stop_price",
        "submit_timeout_at",
        "fill_market_observation_id",
        "trade_id",
        "row_version",
    } <= columns


def test_runtime_schema_facade_is_pinned_to_revision_0005() -> None:
    backend = Path(__file__).resolve().parents[1]
    facade = (backend / "aether_vnext" / "schema.py").read_text(encoding="utf-8")
    assert "schema_v0005" in facade
    migration = (
        backend
        / "alembic"
        / "versions"
        / "0005_aether_vnext_ticket_exit_plan.py"
    ).read_text(encoding="utf-8")
    assert 'revision: str = "0005"' in migration
    assert 'down_revision: Union[str, None] = "0004"' in migration
    assert "exit_plan_id" in migration
    assert "fk_tickets_exit_plan" in migration
