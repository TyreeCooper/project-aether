"""FROZEN revision-0023 SQLAlchemy metadata for the AETHER vNext book of record.

The schema is intentionally independent of legacy app.* persistence. Durable objects
mirror the Master Blueprint lineage chain. Current-state projections are separated
from immutable admission/closure records.
"""
from __future__ import annotations

import sqlalchemy as sa


def build_metadata(*, schema: str | None = "aether_vnext") -> sa.MetaData:
    md = sa.MetaData(schema=schema)

    sa.Table(
        "product_registry_state",
        md,
        sa.Column("asset_id", sa.Text(), primary_key=True),
        sa.Column("registry_version", sa.Text(), nullable=False),
        sa.Column("configuration_hash", sa.Text(), nullable=False),
        sa.Column("lifecycle_state", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "updated_at_utc",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    sa.Table(
        "market_observations",
        md,
        sa.Column("observation_id", sa.Text(), primary_key=True),
        sa.Column("asset_id", sa.Text(), nullable=False, index=True),
        sa.Column("venue", sa.Text(), nullable=False),
        sa.Column("bid", sa.Float()),
        sa.Column("ask", sa.Float()),
        sa.Column("last", sa.Float()),
        sa.Column("mark", sa.Float()),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("exchange_ts", sa.DateTime(timezone=True)),
        sa.Column("received_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("age_ms", sa.BigInteger(), nullable=False),
        sa.Column("spread_abs", sa.Float()),
        sa.Column("spread_bps", sa.Float()),
        sa.Column("session_state", sa.Text(), nullable=False),
        sa.Column("quality_state", sa.Text(), nullable=False),
        sa.Column("fallback_reason", sa.Text()),
        sa.Column("calendar_state", sa.Text(), nullable=False),
        sa.Column("data_version", sa.Text(), nullable=False),
        sa.CheckConstraint("age_ms >= 0", name="ck_market_observation_age_nonnegative"),
    )

    sa.Table(
        "market_ingress_attempts",
        md,
        sa.Column("attempt_id", sa.Text(), primary_key=True),
        sa.Column("asset_id", sa.Text(), nullable=False, index=True),
        sa.Column(
            "configuration_hash",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "policy_snapshots.configuration_hash")),
            nullable=False,
            index=True,
        ),
        sa.Column("runtime_registry_binding_hash", sa.Text()),
        sa.Column("as_of_utc", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("calendar_id", sa.Text(), nullable=False),
        sa.Column("calendar_provider_id", sa.Text()),
        sa.Column(
            "observation_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "market_observations.observation_id")),
        ),
        sa.Column("executable", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("attempted_sources", sa.JSON(), nullable=False),
        sa.Column("rejection_reasons", sa.JSON(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
    )

    sa.Table(
        "policy_snapshots",
        md,
        sa.Column("configuration_hash", sa.Text(), primary_key=True),
        sa.Column("policy_version", sa.Text(), nullable=False, unique=True),
        sa.Column("effective_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("changed_by", sa.Text(), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at_utc",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    sa.Table(
        "governor_state",
        md,
        sa.Column("scope_key", sa.Text(), primary_key=True),
        sa.Column("scope_type", sa.Text(), nullable=False),
        sa.Column("scope_id", sa.Text()),
        sa.Column("governor_state_version", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column(
            "configuration_hash",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "policy_snapshots.configuration_hash")),
            nullable=False,
        ),
        sa.Column("effective_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.CheckConstraint("row_version >= 1", name="ck_governor_row_version_positive"),
    )

    sa.Table(
        "risk_admission_guard",
        md,
        sa.Column("scope_key", sa.Text(), primary_key=True),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column(
            "updated_at_utc",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name="ck_risk_admission_guard_version_positive",
        ),
    )

    sa.Table(
        "broker_account_ledgers",
        md,
        sa.Column("broker_account_id", sa.Text(), primary_key=True),
        sa.Column("cash_available_usd", sa.Float(), nullable=False),
        sa.Column("cash_reserved_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("margin_used_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("margin_available_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("realized_pnl_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("unrealized_pnl_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("fees_accrued_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("carry_accrued_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("settled_cash_usd", sa.Float()),
        sa.Column("reconciliation_state", sa.Text(), nullable=False, server_default="clean"),
        sa.Column("last_reconciled_at", sa.DateTime(timezone=True)),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.CheckConstraint("cash_available_usd >= 0", name="ck_ledger_cash_available_nonnegative"),
        sa.CheckConstraint("cash_reserved_usd >= 0", name="ck_ledger_cash_reserved_nonnegative"),
        sa.CheckConstraint("margin_used_usd >= 0", name="ck_ledger_margin_used_nonnegative"),
        sa.CheckConstraint("margin_available_usd >= 0", name="ck_ledger_margin_available_nonnegative"),
        sa.CheckConstraint("carry_accrued_usd >= 0", name="ck_ledger_carry_nonnegative"),
        sa.CheckConstraint("row_version >= 1", name="ck_ledger_row_version_positive"),
    )

    sa.Table(
        "sleeve_inventory",
        md,
        sa.Column(
            "broker_account_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "broker_account_ledgers.broker_account_id")),
            primary_key=True,
        ),
        sa.Column("asset_id", sa.Text(), primary_key=True),
        sa.Column("inventory_qty", sa.Float(), nullable=False),
        sa.Column("inventory_avg", sa.Float(), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.CheckConstraint(
            "inventory_qty > 0",
            name="ck_sleeve_inventory_qty_positive",
        ),
        sa.CheckConstraint(
            "inventory_avg > 0",
            name="ck_sleeve_inventory_avg_positive",
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name="ck_sleeve_inventory_version_positive",
        ),
    )

    sa.Table(
        "decision_lineage",
        md,
        sa.Column("firm_event_id", sa.Text(), primary_key=True),
        sa.Column("setup_id", sa.Text()),
        sa.Column("ticket_id", sa.Text()),
        sa.Column("order_intent_id", sa.Text()),
        sa.Column("trade_id", sa.Text()),
        sa.Column("asset_id", sa.Text(), nullable=False, index=True),
        sa.Column("route_id", sa.Text(), nullable=False, index=True),
        sa.Column("playbook_id", sa.Text()),
        sa.Column("playbook_version", sa.Text()),
        sa.Column("risk_cluster_id", sa.Text()),
        sa.Column("asset_risk_hitches", sa.JSON()),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column(
            "configuration_hash",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "policy_snapshots.configuration_hash")),
            nullable=False,
        ),
        sa.Column(
            "market_observation_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "market_observations.observation_id")),
        ),
        sa.Column("first_killed_by", sa.Text()),
        sa.Column("first_kill_reason", sa.Text()),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.CheckConstraint("row_version >= 1", name="ck_lineage_row_version_positive"),
    )

    sa.Table(
        "setups",
        md,
        sa.Column("setup_id", sa.Text(), primary_key=True),
        sa.Column(
            "firm_event_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "decision_lineage.firm_event_id")),
        ),
        sa.Column("asset_id", sa.Text(), nullable=False, index=True),
        sa.Column("route_id", sa.Text(), nullable=False, index=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("horizon", sa.Text(), nullable=False),
        sa.Column("playbook_id", sa.Text(), nullable=False),
        sa.Column("playbook_version", sa.Text(), nullable=False),
        sa.Column("risk_cluster_id", sa.Text(), nullable=False),
        sa.Column("asset_risk_hitches", sa.JSON(), nullable=False),
        sa.Column(
            "trigger_bar_close_exchange_ts",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("exit_contract_complete", sa.Boolean(), nullable=False),
        sa.Column("exit_contract_gap", sa.Text()),
        sa.Column("invalidation", sa.Float()),
        sa.Column("quality", sa.Float()),
        sa.Column("intel_pack", sa.JSON(), nullable=False),
        sa.Column("regime_tags", sa.JSON()),
        sa.UniqueConstraint(
            "playbook_id",
            "asset_id",
            "horizon",
            "side",
            "trigger_bar_close_exchange_ts",
            name="uq_setup_playbook_closed_bar_once",
        ),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column(
            "configuration_hash",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "policy_snapshots.configuration_hash")),
            nullable=False,
        ),
        sa.Column(
            "market_observation_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "market_observations.observation_id")),
            nullable=False,
        ),
        sa.Column("first_killed_by", sa.Text()),
        sa.Column("first_kill_reason", sa.Text()),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
    )

    sa.Table(
        "tickets",
        md,
        sa.Column("ticket_id", sa.Text(), primary_key=True),
        sa.Column(
            "exit_plan_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "exit_plans.exit_plan_id")),
        ),
        sa.Column(
            "setup_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "setups.setup_id")),
            nullable=False,
        ),
        sa.Column(
            "firm_event_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "decision_lineage.firm_event_id")),
        ),
        sa.Column("asset_id", sa.Text(), nullable=False, index=True),
        sa.Column("route_id", sa.Text(), nullable=False, index=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("signal_key", sa.Text(), nullable=False, unique=True),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("horizon", sa.Text(), nullable=False),
        sa.Column("stop_price", sa.Float()),
        sa.Column("quantity", sa.Float()),
        sa.Column("modeled_round_trip_cost_pct", sa.Float()),
        sa.Column("reject_code", sa.Text()),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column(
            "configuration_hash",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "policy_snapshots.configuration_hash")),
            nullable=False,
        ),
        sa.Column(
            "market_observation_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "market_observations.observation_id")),
            nullable=False,
        ),
        sa.Column("first_killed_by", sa.Text()),
        sa.Column("first_kill_reason", sa.Text()),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
    )

    sa.Table(
        "exit_plans",
        md,
        sa.Column("exit_plan_id", sa.Text(), primary_key=True),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("hard_stop_price", sa.Float()),
        sa.Column("structure_rule_id", sa.Text()),
        sa.Column("time_stop_deadline_utc", sa.DateTime(timezone=True)),
        sa.Column("trailing_policy", sa.JSON(), nullable=False),
        sa.Column("profit_take_policy", sa.JSON(), nullable=False),
        sa.Column("session_close_policy", sa.Text(), nullable=False),
        sa.Column("stale_mark_policy", sa.Text(), nullable=False),
        sa.Column("governor_halt_behavior", sa.Text(), nullable=False),
        sa.Column("created_from_playbook_version", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
    )

    sa.Table(
        "order_intents",
        md,
        sa.Column("order_intent_id", sa.Text(), primary_key=True),
        sa.Column(
            "broker_account_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "broker_account_ledgers.broker_account_id")),
            nullable=False,
        ),
        sa.Column(
            "exit_plan_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "exit_plans.exit_plan_id")),
        ),
        sa.Column("intent_kind", sa.Text(), nullable=False, server_default="OPEN"),
        sa.Column("exit_reason", sa.Text()),
        sa.Column("position_key", sa.Text(), index=True),
        sa.Column("signal_key", sa.Text(), index=True),
        sa.Column("reserved_cash_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reserved_margin_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("ready_spread_bps", sa.Float()),
        sa.Column("hard_stop_price", sa.Float()),
        sa.Column("submit_timeout_at", sa.DateTime(timezone=True)),
        sa.Column(
            "observation_id_at_fill",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "market_observations.observation_id")),
        ),
        sa.Column("trade_id", sa.Text(), index=True),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column(
            "ticket_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "tickets.ticket_id")),
            nullable=False,
        ),
        sa.Column(
            "firm_event_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "decision_lineage.firm_event_id")),
        ),
        sa.Column("asset_id", sa.Text(), nullable=False, index=True),
        sa.Column("route_id", sa.Text(), nullable=False, index=True),
        sa.Column("broker", sa.Text(), nullable=False),
        sa.Column("venue", sa.Text(), nullable=False),
        sa.Column("symbol_executed", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("requested_qty", sa.Float(), nullable=False),
        sa.Column("order_type", sa.Text(), nullable=False),
        sa.Column("reference_price", sa.Float()),
        sa.Column("expected_fill_price", sa.Float()),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("filled_at", sa.DateTime(timezone=True)),
        sa.Column("filled_qty", sa.Float(), nullable=False, server_default="0"),
        sa.Column("avg_fill_price", sa.Float()),
        sa.Column("reject_code", sa.Text()),
        sa.Column("slip_usd", sa.Float()),
        sa.Column("slip_bps", sa.Float()),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column(
            "configuration_hash",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "policy_snapshots.configuration_hash")),
            nullable=False,
        ),
        sa.Column(
            "observation_id_at_reserve",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "market_observations.observation_id")),
            nullable=False,
        ),
        sa.Column("first_killed_by", sa.Text()),
        sa.Column("first_kill_reason", sa.Text()),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("requested_qty > 0", name="ck_order_intent_requested_qty_positive"),
        sa.CheckConstraint("filled_qty >= 0", name="ck_order_intent_filled_qty_nonnegative"),
        sa.CheckConstraint("reserved_cash_usd >= 0", name="ck_order_intent_reserved_cash_nonnegative"),
        sa.CheckConstraint("reserved_margin_usd >= 0", name="ck_order_intent_reserved_margin_nonnegative"),
        sa.CheckConstraint("version >= 1", name="ck_order_intent_version_positive"),
    )

    sa.Table(
        "risk_admission_reservations",
        md,
        sa.Column(
            "order_intent_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "order_intents.order_intent_id")),
            primary_key=True,
        ),
        sa.Column("asset_id", sa.Text(), nullable=False, index=True),
        sa.Column("cluster_id", sa.Text(), nullable=False, index=True),
        sa.Column("stop_risk_usd", sa.Float(), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column(
            "configuration_hash",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "policy_snapshots.configuration_hash")),
            nullable=False,
        ),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "stop_risk_usd > 0",
            name="ck_risk_admission_stop_risk_positive",
        ),
    )

    sa.Table(
        "open_trades",
        md,
        sa.Column("trade_id", sa.Text(), primary_key=True),
        sa.Column(
            "order_intent_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "order_intents.order_intent_id")),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "ticket_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "tickets.ticket_id")),
            nullable=False,
        ),
        sa.Column(
            "setup_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "setups.setup_id")),
            nullable=False,
        ),
        sa.Column(
            "exit_plan_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "exit_plans.exit_plan_id")),
            nullable=False,
        ),
        sa.Column(
            "firm_event_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "decision_lineage.firm_event_id")),
        ),
        sa.Column("asset_id", sa.Text(), nullable=False, index=True),
        sa.Column("route_id", sa.Text(), nullable=False, index=True),
        sa.Column("position_key", sa.Text(), nullable=False, index=True),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("avg_entry_price", sa.Float(), nullable=False),
        sa.Column("initial_stop_risk_usd", sa.Float(), nullable=False),
        sa.Column("exit_plan_version", sa.Text(), nullable=False),
        sa.Column("exit_plan_payload", sa.JSON(), nullable=False),
        sa.Column("management_telemetry", sa.JSON(), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column(
            "configuration_hash",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "policy_snapshots.configuration_hash")),
            nullable=False,
        ),
        sa.Column(
            "market_observation_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "market_observations.observation_id")),
            nullable=False,
        ),
        sa.Column("opened_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_open_trade_quantity_positive"),
        sa.CheckConstraint(
            "initial_stop_risk_usd >= 0",
            name="ck_open_trade_stop_risk_nonnegative",
        ),
    )

    sa.Table(
        "active_positions",
        md,
        sa.Column("position_key", sa.Text(), primary_key=True),
        sa.Column(
            "trade_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "open_trades.trade_id")),
            nullable=False,
            unique=True,
        ),
        sa.Column("asset_id", sa.Text(), nullable=False, index=True),
        sa.Column("horizon", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_active_position_quantity_positive"),
        sa.CheckConstraint("row_version >= 1", name="ck_active_position_version_positive"),
    )

    sa.Table(
        "closed_trades",
        md,
        sa.Column(
            "trade_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "open_trades.trade_id")),
            primary_key=True,
        ),
        sa.Column(
            "firm_event_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "decision_lineage.firm_event_id")),
        ),
        sa.Column("route_id", sa.Text(), nullable=False, index=True),
        sa.Column("asset_id", sa.Text(), nullable=False, index=True),
        sa.Column("position_key", sa.Text(), nullable=False, index=True),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("avg_entry_price", sa.Float(), nullable=False),
        sa.Column("exit_price", sa.Float(), nullable=False),
        sa.Column("closed_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gross_pnl_usd", sa.Float(), nullable=False),
        sa.Column("net_pnl_usd", sa.Float(), nullable=False),
        sa.Column("total_cost_usd", sa.Float(), nullable=False),
        sa.Column("fees_usd", sa.Float(), nullable=False),
        sa.Column("mfe_usd", sa.Float()),
        sa.Column("mae_usd", sa.Float()),
        sa.Column("capture_efficiency", sa.Float()),
        sa.Column("duration_s", sa.Float(), nullable=False),
        sa.Column("exit_reason", sa.Text(), nullable=False),
        sa.Column("regime_tags", sa.JSON()),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column(
            "configuration_hash",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "policy_snapshots.configuration_hash")),
            nullable=False,
        ),
        sa.Column(
            "market_observation_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "market_observations.observation_id")),
            nullable=False,
        ),
        sa.CheckConstraint("quantity > 0", name="ck_closed_trade_quantity_positive"),
        sa.CheckConstraint("avg_entry_price > 0", name="ck_closed_trade_entry_positive"),
        sa.CheckConstraint("exit_price > 0", name="ck_closed_trade_exit_positive"),
        sa.CheckConstraint("total_cost_usd >= 0", name="ck_closed_trade_cost_nonnegative"),
        sa.CheckConstraint("fees_usd >= 0", name="ck_closed_trade_fees_nonnegative"),
        sa.CheckConstraint("duration_s >= 0", name="ck_closed_trade_duration_nonnegative"),
    )

    sa.Table(
        "research_hypotheses",
        md,
        sa.Column("hypothesis_id", sa.Text(), primary_key=True),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hypothesis_text", sa.Text(), nullable=False),
        sa.Column("economic_rationale", sa.Text(), nullable=False),
        sa.Column("mechanism_class", sa.Text(), nullable=False),
        sa.Column("eligible_assets", sa.JSON(), nullable=False),
        sa.Column("horizon", sa.Text(), nullable=False),
        sa.Column("allowed_sides", sa.JSON(), nullable=False),
        sa.Column("expected_regimes", sa.JSON(), nullable=False),
        sa.Column("falsification_conditions", sa.JSON(), nullable=False),
        sa.Column("required_data", sa.JSON(), nullable=False),
        sa.Column("benchmark_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
    )

    sa.Table(
        "research_hypothesis_annotations",
        md,
        sa.Column("annotation_id", sa.Text(), primary_key=True),
        sa.Column(
            "hypothesis_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "research_hypotheses.hypothesis_id")),
            nullable=False,
            index=True,
        ),
        sa.Column("annotation", sa.Text(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
    )

    sa.Table(
        "research_dataset_snapshots",
        md,
        sa.Column("dataset_snapshot_id", sa.Text(), primary_key=True),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("as_of_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("start_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("asset_ids", sa.JSON(), nullable=False),
        sa.Column("data_version", sa.Text(), nullable=False),
        sa.Column("source_registry_version", sa.Text(), nullable=False),
        sa.Column("product_registry_version", sa.Text(), nullable=False),
        sa.Column("calendar_version", sa.Text(), nullable=False),
        sa.Column("pit", sa.Boolean(), nullable=False),
        sa.Column("missing_data_policy", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.CheckConstraint("pit = TRUE", name="ck_research_dataset_pit_true"),
        sa.CheckConstraint(
            "start_at_utc <= end_at_utc",
            name="ck_research_dataset_window_order",
        ),
        sa.CheckConstraint(
            "end_at_utc <= as_of_utc",
            name="ck_research_dataset_no_future_data",
        ),
    )

    sa.Table(
        "research_experiments",
        md,
        sa.Column("experiment_id", sa.Text(), primary_key=True),
        sa.Column(
            "hypothesis_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "research_hypotheses.hypothesis_id")),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "parent_experiment_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "research_experiments.experiment_id")),
        ),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("frozen_at_utc", sa.DateTime(timezone=True)),
        sa.Column("research_state", sa.Text(), nullable=False),
        sa.Column("parameter_spec", sa.JSON(), nullable=False),
        sa.Column("parameter_space_hash", sa.Text(), nullable=False),
        sa.Column(
            "dataset_snapshot_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "research_dataset_snapshots.dataset_snapshot_id")),
            nullable=False,
        ),
        sa.Column("code_commit_sha", sa.Text(), nullable=False),
        sa.Column("configuration_hash", sa.Text(), nullable=False, index=True),
        sa.Column("owner", sa.Text(), nullable=False),
        sa.Column(
            "supersedes_experiment_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "research_experiments.experiment_id")),
        ),
    )

    sa.Table(
        "backtest_runs",
        md,
        sa.Column("backtest_run_id", sa.Text(), primary_key=True),
        sa.Column(
            "experiment_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "research_experiments.experiment_id")),
            nullable=False,
            index=True,
        ),
        sa.Column("run_type", sa.Text(), nullable=False),
        sa.Column(
            "dataset_snapshot_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "research_dataset_snapshots.dataset_snapshot_id")),
            nullable=False,
        ),
        sa.Column("playbook_id", sa.Text(), nullable=False),
        sa.Column("playbook_version", sa.Text(), nullable=False),
        sa.Column("code_commit_sha", sa.Text(), nullable=False),
        sa.Column("configuration_hash", sa.Text(), nullable=False, index=True),
        sa.Column("cost_model_version", sa.Text(), nullable=False),
        sa.Column("execution_model_version", sa.Text(), nullable=False),
        sa.Column("random_seed", sa.BigInteger()),
        sa.Column("started_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at_utc", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("integrity_flags", sa.JSON(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
    )

    sa.Table(
        "fold_results",
        md,
        sa.Column("fold_result_id", sa.Text(), primary_key=True),
        sa.Column(
            "backtest_run_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "backtest_runs.backtest_run_id")),
            nullable=False,
            index=True,
        ),
        sa.Column("fold_index", sa.Integer(), nullable=False),
        sa.Column("train_start_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("train_end_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("test_start_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("test_end_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("net_pnl", sa.Float(), nullable=False),
        sa.Column("expectancy_r", sa.Float(), nullable=False),
        sa.Column("profit_factor", sa.Float(), nullable=False),
        sa.Column("stop_rate", sa.Float(), nullable=False),
        sa.Column("max_drawdown", sa.Float(), nullable=False),
        sa.Column("cost_drag", sa.Float(), nullable=False),
        sa.Column("benchmark_result", sa.JSON(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("failure_reasons", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "backtest_run_id",
            "fold_index",
            name="uq_fold_result_run_index",
        ),
        sa.CheckConstraint("n >= 0", name="ck_fold_result_n_nonnegative"),
        sa.CheckConstraint(
            "train_start_utc <= train_end_utc "
            "AND train_end_utc < test_start_utc "
            "AND test_start_utc <= test_end_utc",
            name="ck_fold_result_chronological",
        ),
    )

    sa.Table(
        "traffic_experiments",
        md,
        sa.Column("experiment_id", sa.Text(), primary_key=True),
        sa.Column("change_family", sa.Text(), nullable=False),
        sa.Column(
            "control_configuration_hash",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "policy_snapshots.configuration_hash")),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "treatment_configuration_hash",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "policy_snapshots.configuration_hash")),
            nullable=False,
            index=True,
        ),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("owner", sa.Text(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "control_configuration_hash <> treatment_configuration_hash",
            name="ck_traffic_experiment_distinct_configs",
        ),
    )

    sa.Table(
        "traffic_shadow_comparisons",
        md,
        sa.Column("shadow_comparison_id", sa.Text(), primary_key=True),
        sa.Column(
            "experiment_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "traffic_experiments.experiment_id")),
            nullable=False,
            index=True,
        ),
        sa.Column("opportunity_id", sa.Text(), nullable=False, index=True),
        sa.Column("current_configuration_hash", sa.Text(), nullable=False),
        sa.Column("prior_configuration_hash", sa.Text(), nullable=False),
        sa.Column("would_pass_under_prior_policy", sa.Boolean(), nullable=False),
        sa.Column("order_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("evaluated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "order_created = FALSE",
            name="ck_shadow_comparison_no_order",
        ),
        sa.CheckConstraint(
            "current_configuration_hash <> prior_configuration_hash",
            name="ck_shadow_comparison_distinct_configs",
        ),
    )

    sa.Table(
        "profitability_readiness_assessments",
        md,
        sa.Column("assessment_id", sa.Text(), primary_key=True),
        sa.Column("readiness_policy_version", sa.Text(), nullable=False),
        sa.Column("firm_snapshot_hash", sa.Text(), nullable=False, index=True),
        sa.Column("burn_in_start_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("burn_in_end_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("as_of_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("burn_in_duration_s", sa.Float(), nullable=False),
        sa.Column("active_route_count", sa.Integer(), nullable=False),
        sa.Column("trusted_route_count", sa.Integer(), nullable=False),
        sa.Column("oos_positive_route_count", sa.Integer(), nullable=False),
        sa.Column("sustained_operation_satisfied", sa.Boolean()),
        sa.Column("sustained_operation_policy_version", sa.Text()),
        sa.Column("oos_trusted_sufficiency_satisfied", sa.Boolean()),
        sa.Column("oos_trusted_sufficiency_policy_version", sa.Text()),
        sa.Column("profitability_ready", sa.Boolean(), nullable=False),
        sa.Column(
            "live_execution_authorized",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("blocking_reasons", sa.JSON(), nullable=False),
        sa.Column("unresolved_rules", sa.JSON(), nullable=False),
        sa.Column("unresolved_accounting_defects", sa.JSON(), nullable=False),
        sa.Column("unresolved_model_defects", sa.JSON(), nullable=False),
        sa.Column("evidence_checks", sa.JSON(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "burn_in_start_at_utc <= burn_in_end_at_utc "
            "AND burn_in_end_at_utc <= as_of_utc",
            name="ck_profitability_readiness_time_order",
        ),
        sa.CheckConstraint(
            "active_route_count >= 0 "
            "AND trusted_route_count >= 0 "
            "AND oos_positive_route_count >= 0",
            name="ck_profitability_readiness_counts_nonnegative",
        ),
        sa.CheckConstraint(
            "trusted_route_count <= active_route_count "
            "AND oos_positive_route_count <= active_route_count",
            name="ck_profitability_readiness_route_counts",
        ),
        sa.CheckConstraint(
            "live_execution_authorized = FALSE",
            name="ck_profitability_readiness_never_live_authority",
        ),
    )

    sa.Table(
        "forward_paper_campaigns",
        md,
        sa.Column("campaign_id", sa.Text(), primary_key=True),
        sa.Column(
            "configuration_hash",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "policy_snapshots.configuration_hash")),
            nullable=False,
            index=True,
        ),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("baseline_snapshot_hash", sa.Text(), nullable=False),
        sa.Column("started_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("forced_entry_enabled", sa.Boolean(), nullable=False),
        sa.Column("natural_setup_only", sa.Boolean(), nullable=False),
        sa.Column("real_market_time_required", sa.Boolean(), nullable=False),
        sa.Column("pit_inputs_required", sa.Boolean(), nullable=False),
        sa.Column("modeled_cost_capture_required", sa.Boolean(), nullable=False),
        sa.Column("observed_cost_capture_required", sa.Boolean(), nullable=False),
        sa.Column("route_pnl_accounting_required", sa.Boolean(), nullable=False),
        sa.Column("disposition_accounting_required", sa.Boolean(), nullable=False),
        sa.Column("no_cherry_pick", sa.Boolean(), nullable=False),
        sa.Column("historical_comparison_separate", sa.Boolean(), nullable=False),
        sa.Column("live_blocked", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "forced_entry_enabled = FALSE",
            name="ck_forward_campaign_forced_entry_off",
        ),
        sa.CheckConstraint(
            "natural_setup_only = TRUE "
            "AND real_market_time_required = TRUE "
            "AND pit_inputs_required = TRUE "
            "AND modeled_cost_capture_required = TRUE "
            "AND observed_cost_capture_required = TRUE "
            "AND route_pnl_accounting_required = TRUE "
            "AND disposition_accounting_required = TRUE "
            "AND no_cherry_pick = TRUE "
            "AND historical_comparison_separate = TRUE "
            "AND live_blocked = TRUE",
            name="ck_forward_campaign_c91_invariants",
        ),
        sa.CheckConstraint(
            "started_at_utc <= created_at_utc",
            name="ck_forward_campaign_time_order",
        ),
    )

    sa.Table(
        "forward_paper_campaign_routes",
        md,
        sa.Column("campaign_route_id", sa.Text(), primary_key=True),
        sa.Column(
            "campaign_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "forward_paper_campaigns.campaign_id")),
            nullable=False,
            index=True,
        ),
        sa.Column("route_id", sa.Text(), nullable=False, index=True),
        sa.Column("playbook_id", sa.Text(), nullable=False),
        sa.Column("playbook_version", sa.Text(), nullable=False),
        sa.Column("configuration_hash", sa.Text(), nullable=False),
        sa.Column("runtime_registry_binding_hash", sa.Text(), nullable=False),
        sa.Column("historical_validation_window_ids", sa.JSON(), nullable=False),
        sa.Column("historical_metrics_snapshot_hash", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "campaign_id",
            "route_id",
            "playbook_id",
            name="uq_forward_campaign_route_playbook",
        ),
    )

    sa.Table(
        "forward_paper_campaign_windows",
        md,
        sa.Column("campaign_window_id", sa.Text(), primary_key=True),
        sa.Column(
            "campaign_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "forward_paper_campaigns.campaign_id")),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "campaign_route_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "forward_paper_campaign_routes.campaign_route_id")),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "evidence_window_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "evidence_windows.evidence_window_id")),
            nullable=False,
            unique=True,
        ),
        sa.Column("linked_at_utc", sa.DateTime(timezone=True), nullable=False),
    )

    sa.Table(
        "evidence_windows",
        md,
        sa.Column("evidence_window_id", sa.Text(), primary_key=True),
        sa.Column("route_id", sa.Text(), nullable=False, index=True),
        sa.Column("playbook_id", sa.Text(), nullable=False),
        sa.Column("playbook_version", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column(
            "configuration_hash",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "policy_snapshots.configuration_hash")),
            nullable=False,
            index=True,
        ),
        sa.Column("sample_domain", sa.Text(), nullable=False, index=True),
        sa.Column("first_timestamp_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_timestamp_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("immutable_trade_ids", sa.JSON(), nullable=False),
        sa.Column("metrics_snapshot_hash", sa.Text(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "n > 0",
            name="ck_evidence_windows_n_positive",
        ),
        sa.CheckConstraint(
            "first_timestamp_utc <= last_timestamp_utc",
            name="ck_evidence_windows_timestamp_order",
        ),
    )

    sa.Table(
        "held_out_evidence_provenance",
        md,
        sa.Column(
            "evidence_window_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "evidence_windows.evidence_window_id")),
            primary_key=True,
        ),
        sa.Column(
            "backtest_run_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "backtest_runs.backtest_run_id")),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "dataset_snapshot_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "research_dataset_snapshots.dataset_snapshot_id")),
            nullable=False,
            index=True,
        ),
        sa.Column("fold_result_ids", sa.JSON(), nullable=False),
        sa.Column("provenance_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
    )

    sa.Table(
        "profitability_evidence",
        md,
        sa.Column("evidence_id", sa.Text(), primary_key=True),
        sa.Column("route_id", sa.Text(), nullable=False, index=True),
        sa.Column("playbook_id", sa.Text(), nullable=False),
        sa.Column("playbook_version", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column(
            "configuration_hash",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "policy_snapshots.configuration_hash")),
            nullable=False,
            index=True,
        ),
        sa.Column("data_version", sa.Text(), nullable=False),
        sa.Column("fill_model_version", sa.Text(), nullable=False),
        sa.Column("fee_schedule_version", sa.Text(), nullable=False),
        sa.Column("in_sample_window", sa.JSON()),
        sa.Column("oos_windows", sa.JSON(), nullable=False),
        sa.Column("n_trades", sa.Integer(), nullable=False),
        sa.Column("net_expectancy_usd", sa.Float(), nullable=False),
        sa.Column("profit_factor", sa.Float(), nullable=False),
        sa.Column("win_rate", sa.Float(), nullable=False),
        sa.Column("avg_win_usd", sa.Float(), nullable=False),
        sa.Column("avg_loss_usd", sa.Float(), nullable=False),
        sa.Column("stop_rate", sa.Float(), nullable=False),
        sa.Column("max_drawdown_usd", sa.Float(), nullable=False),
        sa.Column("max_drawdown_pct", sa.Float(), nullable=False),
        sa.Column("median_duration_s", sa.Float(), nullable=False),
        sa.Column("capture_efficiency", sa.Float(), nullable=False),
        sa.Column("cost_sensitivity", sa.JSON(), nullable=False),
        sa.Column("regime_matrix", sa.JSON(), nullable=False),
        sa.Column("benchmark_result", sa.JSON(), nullable=False),
        sa.Column("capacity_result", sa.JSON(), nullable=False),
        sa.Column("portfolio_contribution", sa.JSON(), nullable=False),
        sa.Column("model_risks", sa.JSON(), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("reviewer", sa.Text(), nullable=False),
        sa.Column("as_of_utc", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "n_trades >= 0",
            name="ck_profitability_evidence_n_nonnegative",
        ),
        sa.CheckConstraint(
            "win_rate >= 0 AND win_rate <= 1",
            name="ck_profitability_evidence_win_rate_unit",
        ),
        sa.CheckConstraint(
            "stop_rate >= 0 AND stop_rate <= 1",
            name="ck_profitability_evidence_stop_rate_unit",
        ),
        sa.CheckConstraint(
            "median_duration_s >= 0",
            name="ck_profitability_evidence_duration_nonnegative",
        ),
    )

    sa.Table(
        "decay_review_requests",
        md,
        sa.Column("decay_request_id", sa.Text(), primary_key=True),
        sa.Column("route_id", sa.Text(), nullable=False, index=True),
        sa.Column("playbook_id", sa.Text(), nullable=False),
        sa.Column("playbook_version", sa.Text(), nullable=False),
        sa.Column(
            "configuration_hash",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "policy_snapshots.configuration_hash")),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "reference_evidence_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "profitability_evidence.evidence_id")),
            nullable=False,
        ),
        sa.Column(
            "recent_evidence_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "profitability_evidence.evidence_id")),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("request_review", sa.Boolean(), nullable=False),
        sa.Column("materiality_decision", sa.Boolean()),
        sa.Column("materiality_policy_version", sa.Text()),
        sa.Column("metric_deltas", sa.JSON(), nullable=False),
        sa.Column("deterioration_dimensions", sa.JSON(), nullable=False),
        sa.Column("unresolved_rules", sa.JSON(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "reference_evidence_id <> recent_evidence_id",
            name="ck_decay_reference_recent_distinct",
        ),
    )

    sa.Table(
        "review_cards",
        md,
        sa.Column("review_card_id", sa.Text(), primary_key=True),
        sa.Column(
            "firm_event_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "decision_lineage.firm_event_id")),
        ),
        sa.Column(
            "trade_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "closed_trades.trade_id")),
        ),
        sa.Column("route_id", sa.Text(), nullable=False, index=True),
        sa.Column("playbook_id", sa.Text(), nullable=False),
        sa.Column("playbook_version", sa.Text(), nullable=False),
        sa.Column("as_of_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_state", sa.Text(), nullable=False),
        sa.Column(
            "evidence_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "profitability_evidence.evidence_id")),
        ),
        sa.Column("decision_reason", sa.Text(), nullable=False),
        sa.Column("reviewer", sa.Text(), nullable=False),
        sa.Column(
            "configuration_hash",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "policy_snapshots.configuration_hash")),
            nullable=False,
        ),
    )

    sa.Table(
        "route_review_state",
        md,
        sa.Column("route_id", sa.Text(), primary_key=True),
        sa.Column("evidence_state", sa.Text(), nullable=False),
        sa.Column("operational_state", sa.Text(), nullable=False),
        sa.Column(
            "review_card_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "review_cards.review_card_id")),
        ),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.CheckConstraint("row_version >= 1", name="ck_route_review_version_positive"),
    )

    sa.Table(
        "signal_consumptions",
        md,
        sa.Column("signal_key", sa.Text(), primary_key=True),
        sa.Column(
            "order_intent_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "order_intents.order_intent_id")),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "trade_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "open_trades.trade_id")),
            nullable=False,
            unique=True,
        ),
        sa.Column("consumed_at_utc", sa.DateTime(timezone=True), nullable=False),
    )

    sa.Table(
        "mutation_idempotency",
        md,
        sa.Column("idempotency_key", sa.Text(), primary_key=True),
        sa.Column("mutation_type", sa.Text(), nullable=False),
        sa.Column("aggregate_type", sa.Text(), nullable=False),
        sa.Column("aggregate_id", sa.Text(), nullable=False),
        sa.Column("result_payload_hash", sa.Text()),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
    )

    sa.Table(
        "ledger_transfers",
        md,
        sa.Column("transfer_id", sa.Text(), primary_key=True),
        sa.Column(
            "from_ledger",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "broker_account_ledgers.broker_account_id")),
            nullable=False,
        ),
        sa.Column(
            "to_ledger",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "broker_account_ledgers.broker_account_id")),
            nullable=False,
        ),
        sa.Column("usd", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        sa.CheckConstraint("usd > 0", name="ck_ledger_transfer_usd_positive"),
        sa.CheckConstraint("from_ledger <> to_ledger", name="ck_ledger_transfer_distinct"),
    )

    sa.Table(
        "reconciliation_runs",
        md,
        sa.Column("reconciliation_id", sa.Text(), primary_key=True),
        sa.Column("broker_account_id", sa.Text(), nullable=False, index=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("started_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at_utc", sa.DateTime(timezone=True)),
        sa.Column("cash_delta_usd", sa.Float()),
        sa.Column("margin_delta_usd", sa.Float()),
        sa.Column("position_delta_count", sa.Integer()),
        sa.Column("fill_delta_count", sa.Integer()),
        sa.Column("details", sa.JSON(), nullable=False),
    )

    sa.Table(
        "event_ledger",
        md,
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("aggregate_type", sa.Text(), nullable=False, index=True),
        sa.Column("aggregate_id", sa.Text(), nullable=False, index=True),
        sa.Column("prior_state", sa.Text()),
        sa.Column("new_state", sa.Text(), nullable=False),
        sa.Column("seat", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column(
            "configuration_hash",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "policy_snapshots.configuration_hash")),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "market_observation_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "market_observations.observation_id")),
        ),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )

    return md


def _fk(schema: str | None, target: str) -> str:
    return f"{schema}.{target}" if schema else target


METADATA = build_metadata()
