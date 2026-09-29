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
        "market_ingress_attempts",
        "shortability_evidence",
        "policy_snapshots",
        "governor_state",
        "risk_admission_guard",
        "broker_account_ledgers",
        "decision_lineage",
        "setups",
        "tickets",
        "exit_plans",
        "order_intents",
        "risk_admission_reservations",
        "open_trades",
        "active_positions",
        "closed_trades",
        "evidence_windows",
        "held_out_evidence_provenance",
        "profitability_evidence",
        "decay_review_requests",
        "research_hypotheses",
        "research_hypothesis_annotations",
        "research_dataset_snapshots",
        "research_bars",
        "research_experiments",
        "backtest_runs",
        "fold_results",
        "research_promotions",
        "traffic_experiments",
        "traffic_shadow_comparisons",
        "profitability_readiness_assessments",
        "forward_paper_campaigns",
        "forward_paper_campaign_routes",
        "forward_paper_campaign_windows",
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
    assert "profitability_evidence.evidence_id" in targets("review_cards")
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
        "order_intent_id",
        "ticket_id",
        "trade_id",
        "broker_account_id",
        "venue",
        "symbol_executed",
        "side",
        "requested_qty",
        "filled_qty",
        "order_type",
        "reference_price",
        "expected_fill_price",
        "avg_fill_price",
        "state",
        "reject_code",
        "slip_usd",
        "slip_bps",
        "submitted_at",
        "acknowledged_at",
        "filled_at",
        "submit_timeout_at",
        "shortability_evidence_id",
        "idempotency_key",
        "observation_id_at_reserve",
        "observation_id_at_fill",
        "version",
        "exit_plan_id",
        "intent_kind",
        "position_key",
        "signal_key",
        "reserved_cash_usd",
        "reserved_margin_usd",
        "ready_spread_bps",
        "hard_stop_price",
    } <= columns
    assert "symbol" not in columns
    assert "qty" not in columns
    assert "expected_fill" not in columns
    assert "slippage_usd" not in columns
    assert "slippage_bps" not in columns
    assert "fill_market_observation_id" not in columns


def test_runtime_schema_facade_is_pinned_to_revision_0030() -> None:
    _, store = _engine_and_store()
    backend = Path(__file__).resolve().parents[1]
    facade = (backend / "aether_vnext" / "schema.py").read_text(encoding="utf-8")
    assert "schema_v0030" in facade

    campaign_migration = (
        backend
        / "alembic"
        / "versions"
        / "0020_aether_vnext_forward_paper_campaign.py"
    ).read_text(encoding="utf-8")
    assert 'revision: str = "0020"' in campaign_migration
    assert "forward_paper_campaigns" in campaign_migration
    assert "ck_forward_campaign_c91_invariants" in campaign_migration

    provenance_migration = (
        backend
        / "alembic"
        / "versions"
        / "0021_aether_vnext_held_out_provenance.py"
    ).read_text(encoding="utf-8")
    assert 'revision: str = "0021"' in provenance_migration
    assert 'down_revision: Union[str, None] = "0020"' in provenance_migration
    assert "held_out_evidence_provenance" in provenance_migration
    assert "backtest_run_id" in provenance_migration
    assert "fold_result_ids" in provenance_migration
    assert "trg_held_out_evidence_provenance_immutable" in provenance_migration
    assert "reject_immutable_mutation" in provenance_migration

    registry_binding_migration = (
        backend
        / "alembic"
        / "versions"
        / "0022_aether_vnext_campaign_registry_binding.py"
    ).read_text(encoding="utf-8")
    assert 'revision: str = "0022"' in registry_binding_migration
    assert 'down_revision: Union[str, None] = "0021"' in registry_binding_migration
    assert "runtime_registry_binding_hash" in registry_binding_migration
    assert "forward_paper_campaign_routes" in registry_binding_migration

    campaign_routes = store.tables["forward_paper_campaign_routes"]
    assert "runtime_registry_binding_hash" in campaign_routes.c

    ingress_migration = (
        backend
        / "alembic"
        / "versions"
        / "0023_aether_vnext_market_ingress_attempts.py"
    ).read_text(encoding="utf-8")
    assert 'revision: str = "0023"' in ingress_migration
    assert 'down_revision: Union[str, None] = "0022"' in ingress_migration
    assert "market_ingress_attempts" in ingress_migration
    assert "trg_market_ingress_attempts_immutable" in ingress_migration

    ingress = store.tables["market_ingress_attempts"]
    assert {
        "attempt_id",
        "asset_id",
        "configuration_hash",
        "runtime_registry_binding_hash",
        "as_of_utc",
        "calendar_id",
        "calendar_provider_id",
        "observation_id",
        "executable",
        "reason",
        "attempted_sources",
        "rejection_reasons",
        "created_at_utc",
    } <= set(ingress.c.keys())


    shortability_migration = (
        backend
        / "alembic"
        / "versions"
        / "0024_aether_vnext_shortability_evidence.py"
    ).read_text(encoding="utf-8")
    assert 'revision: str = "0024"' in shortability_migration
    assert 'down_revision: Union[str, None] = "0023"' in shortability_migration
    assert "shortability_evidence" in shortability_migration
    assert "trg_shortability_evidence_immutable" in shortability_migration

    shortability = store.tables["shortability_evidence"]
    assert {
        "evidence_id",
        "asset_id",
        "configuration_hash",
        "runtime_registry_binding_hash",
        "provider_id",
        "market_data_contract_id",
        "shortable_shares",
        "fee_rate_raw",
        "shortable_raw",
        "market_data_availability",
        "provider_updated_at_utc",
        "received_at_utc",
        "adapter_version",
        "created_at_utc",
    } <= set(shortability.c.keys())


    research_bar_migration = (
        backend
        / "alembic"
        / "versions"
        / "0025_aether_vnext_research_bars.py"
    ).read_text(encoding="utf-8")
    assert 'revision: str = "0025"' in research_bar_migration
    assert 'down_revision: Union[str, None] = "0024"' in research_bar_migration
    assert "research_bars" in research_bar_migration
    assert "trg_research_bars_immutable" in research_bar_migration

    research_bars = store.tables["research_bars"]
    assert {
        "research_bar_id",
        "dataset_snapshot_id",
        "asset_id",
        "interval_seconds",
        "bucket_open_utc",
        "bucket_close_utc",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "source_id",
        "source_data_version",
        "source_ref",
        "available_at_utc",
    } <= set(research_bars.c.keys())


    promotion_migration = (
        backend
        / "alembic"
        / "versions"
        / "0026_aether_vnext_research_promotions.py"
    ).read_text(encoding="utf-8")
    assert 'revision: str = "0026"' in promotion_migration
    assert 'down_revision: Union[str, None] = "0025"' in promotion_migration
    assert "research_promotions" in promotion_migration
    assert "trg_research_promotions_immutable" in promotion_migration
    assert "reject_immutable_mutation" in promotion_migration

    promotions = store.tables["research_promotions"]
    assert {
        "promotion_id",
        "route_id",
        "playbook_version",
        "from_evidence_state",
        "to_evidence_state",
        "review_card_id",
        "evidence_window_id",
        "reviewer",
        "approver",
        "decided_at_utc",
        "decision_reason",
        "configuration_hash",
        "n_reset",
        "supersedes",
    } <= set(promotions.c.keys())

    intelligence_migration = (
        backend
        / "alembic"
        / "versions"
        / "0027_aether_vnext_intelligence_persistence.py"
    ).read_text(encoding="utf-8")
    assert 'revision: str = "0027"' in intelligence_migration
    assert 'down_revision: Union[str, None] = "0026"' in intelligence_migration
    for table_name in (
        "intelligence_sources",
        "source_trust_decisions",
        "intelligence_health_snapshots",
        "cross_source_conflict_assessments",
        "event_reaction_measurements",
        "event_reaction_rollups",
    ):
        assert table_name in intelligence_migration
        assert table_name in store.tables

    assert "def _immutable_trigger(table_name: str) -> None:" in intelligence_migration
    assert "BEFORE UPDATE OR DELETE" in intelligence_migration
    assert "_immutable_trigger(table_name)" in intelligence_migration
    assert "reject_immutable_mutation" in intelligence_migration

    sources = store.tables["intelligence_sources"]
    assert {
        "source_id",
        "asset_id",
        "source_type",
        "platform",
        "name",
        "url",
        "tier",
        "trust_state",
        "origin",
        "ingestion_mode",
        "trade_influence_enabled",
        "operator_approved_by",
        "operator_approved_at_utc",
        "row_version",
    } <= set(sources.c.keys())

    reactions = store.tables["event_reaction_measurements"]
    assert {
        "observation_id",
        "event_id",
        "asset_id",
        "event_at_utc",
        "information_available_at_utc",
        "horizon_seconds",
        "observed_at_utc",
        "return_value",
        "market_data_version",
        "research_only",
    } <= set(reactions.c.keys())

    news_migration = (
        backend
        / "alembic"
        / "versions"
        / "0028_aether_vnext_news_ledger.py"
    ).read_text(encoding="utf-8")
    assert 'revision: str = "0028"' in news_migration
    assert 'down_revision: Union[str, None] = "0027"' in news_migration
    assert "def _immutable_trigger(table_name: str) -> None:" in news_migration
    assert "BEFORE UPDATE OR DELETE" in news_migration
    assert "reject_immutable_mutation" in news_migration
    for table_name in (
        "news_sources",
        "raw_news_items",
        "normalized_events",
        "event_asset_links",
        "event_market_responses",
        "historical_analog_runs",
    ):
        assert table_name in news_migration
        assert table_name in store.tables

    normalized = store.tables["normalized_events"]
    assert {
        "event_id",
        "event_cluster_id",
        "event_type",
        "source_news_item_ids",
        "assets",
        "clusters",
        "canonical_event_at_utc",
        "information_available_at_utc",
        "scheduled",
        "expected",
        "consensus",
        "actual",
        "surprise_magnitude",
        "direction",
        "severity",
        "novelty",
        "confidence",
        "market_scope",
        "normalizer_version",
    } <= set(normalized.c.keys())

    analogs = store.tables["historical_analog_runs"]
    assert {
        "analog_run_id",
        "query_event_or_state_id",
        "feature_spec_version",
        "as_of_utc",
        "eligible_history_cutoff_utc",
        "matched_event_ids",
        "similarity_scores",
        "outcome_distribution",
        "created_at_utc",
        "research_only",
    } <= set(analogs.c.keys())

    audit_migration = (
        backend
        / "alembic"
        / "versions"
        / "0029_aether_vnext_intelligence_shadow_audit.py"
    ).read_text(encoding="utf-8")
    assert 'revision: str = "0029"' in audit_migration
    assert 'down_revision: Union[str, None] = "0028"' in audit_migration
    assert "trg_intelligence_shadow_audits_immutable" in audit_migration
    assert "BEFORE UPDATE OR DELETE" in audit_migration

    audits = store.tables["intelligence_shadow_audits"]
    assert {
        "audit_id",
        "opportunity_id",
        "route_id",
        "as_of_utc",
        "baseline_configuration_hash",
        "shadow_configuration_hash",
        "enabled_components",
        "baseline_outcome",
        "shadow_outcome",
        "evidence_ids",
        "research_only",
        "order_created",
        "trade_influence_enabled",
    } <= set(audits.c.keys())

    memory_migration = (
        backend
        / "alembic"
        / "versions"
        / "0030_aether_vnext_institutional_memory.py"
    ).read_text(encoding="utf-8")
    assert 'revision: str = "0030"' in memory_migration
    assert 'down_revision: Union[str, None] = "0029"' in memory_migration
    assert "def _immutable_trigger(table_name: str) -> None:" in memory_migration
    assert "BEFORE UPDATE OR DELETE" in memory_migration
    assert "reject_immutable_mutation" in memory_migration
    for table_name in (
        "pnl_attributions",
        "institutional_memories",
        "failure_archive_entries",
        "counterfactual_replays",
        "experience_coverage_snapshots",
    ):
        assert table_name in memory_migration
        assert table_name in store.tables

    attributions = store.tables["pnl_attributions"]
    assert {
        "attribution_id",
        "firm_id",
        "mechanism_id",
        "playbook_id",
        "playbook_version",
        "route_id",
        "asset_id",
        "horizon",
        "side",
        "regime_id",
        "trade_id",
        "configuration_hash",
        "net_pnl_usd",
        "components",
        "attributed_at_utc",
        "source_record_ids",
    } <= set(attributions.c.keys())

    memories = store.tables["institutional_memories"]
    assert {
        "memory_id",
        "trade_id",
        "route_id",
        "market_state_ref",
        "information_state_ref",
        "signal_ref",
        "decision_ref",
        "expected_outcome_ref",
        "actual_outcome_ref",
        "execution_quality_ref",
        "risk_state_ref",
        "success_failure_reason",
        "lesson",
        "future_relevance",
        "occurred_at_utc",
        "recorded_at_utc",
        "source_record_ids",
    } <= set(memories.c.keys())

    counterfactuals = store.tables["counterfactual_replays"]
    assert {
        "replay_id",
        "original_memory_id",
        "variation_keys",
        "hypothetical_result_ref",
        "created_at_utc",
        "hypothetical",
        "independent_evidence_credit",
    } <= set(counterfactuals.c.keys())


def test_phase6_atomic_risk_admission_schema_is_explicit() -> None:
    _, store = _engine_and_store()
    guard = store.tables["risk_admission_guard"]
    reservations = store.tables["risk_admission_reservations"]
    assert tuple(guard.primary_key.columns.keys()) == ("scope_key",)
    assert "row_version" in guard.c
    assert tuple(reservations.primary_key.columns.keys()) == ("order_intent_id",)
    assert {
        "asset_id",
        "cluster_id",
        "stop_risk_usd",
        "policy_version",
        "configuration_hash",
        "created_at_utc",
    } <= set(reservations.c.keys())


def test_closed_trade_is_self_contained_execution_evidence() -> None:
    _, store = _engine_and_store()
    columns = set(store.tables["closed_trades"].c.keys())
    assert {
        "trade_id",
        "route_id",
        "asset_id",
        "position_key",
        "side",
        "quantity",
        "avg_entry_price",
        "exit_price",
        "closed_at_utc",
        "gross_pnl_usd",
        "net_pnl_usd",
        "total_cost_usd",
        "fees_usd",
        "mfe_usd",
        "mae_usd",
        "capture_efficiency",
        "duration_s",
        "exit_reason",
        "policy_version",
        "configuration_hash",
        "market_observation_id",
        "regime_tags",
    } <= columns


def test_close_order_intent_persists_exit_reason() -> None:
    _, store = _engine_and_store()
    assert "exit_reason" in store.tables["order_intents"].c


def test_broker_ledger_and_normalized_inventory_cover_v421_sleeve_fields() -> None:
    _, store = _engine_and_store()
    ledger_columns = set(store.tables["broker_account_ledgers"].c.keys())
    assert {
        "cash_available_usd",
        "cash_reserved_usd",
        "margin_used_usd",
        "margin_available_usd",
        "realized_pnl_usd",
        "unrealized_pnl_usd",
        "fees_accrued_usd",
        "carry_accrued_usd",
        "settled_cash_usd",
        "last_reconciled_at",
        "reconciliation_state",
        "row_version",
    } <= ledger_columns
    assert "inventory_qty" not in ledger_columns
    assert "inventory_avg" not in ledger_columns

    inventory = store.tables["sleeve_inventory"]
    assert {
        "broker_account_id",
        "asset_id",
        "inventory_qty",
        "inventory_avg",
        "updated_at_utc",
        "row_version",
    } <= set(inventory.c.keys())
    assert tuple(inventory.primary_key.columns.keys()) == (
        "broker_account_id",
        "asset_id",
    )
