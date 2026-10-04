"""FROZEN revision-0004 SQLAlchemy metadata for the AETHER vNext book of record.

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
        sa.Column("settled_cash_usd", sa.Float()),
        sa.Column("reconciliation_state", sa.Text(), nullable=False, server_default="clean"),
        sa.Column("last_reconciled_at", sa.DateTime(timezone=True)),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.CheckConstraint("cash_available_usd >= 0", name="ck_ledger_cash_available_nonnegative"),
        sa.CheckConstraint("cash_reserved_usd >= 0", name="ck_ledger_cash_reserved_nonnegative"),
        sa.CheckConstraint("margin_used_usd >= 0", name="ck_ledger_margin_used_nonnegative"),
        sa.CheckConstraint("margin_available_usd >= 0", name="ck_ledger_margin_available_nonnegative"),
        sa.CheckConstraint("row_version >= 1", name="ck_ledger_row_version_positive"),
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
        sa.Column("invalidation", sa.Float()),
        sa.Column("quality", sa.Float()),
        sa.Column("intel_pack", sa.JSON(), nullable=False),
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
        sa.Column("position_key", sa.Text(), index=True),
        sa.Column("signal_key", sa.Text(), index=True),
        sa.Column("reserved_cash_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reserved_margin_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("ready_spread_bps", sa.Float()),
        sa.Column("hard_stop_price", sa.Float()),
        sa.Column("submit_timeout_at", sa.DateTime(timezone=True)),
        sa.Column(
            "fill_market_observation_id",
            sa.Text(),
            sa.ForeignKey(_fk(schema, "market_observations.observation_id")),
        ),
        sa.Column("trade_id", sa.Text(), index=True),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
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
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("qty", sa.Float(), nullable=False),
        sa.Column("order_type", sa.Text(), nullable=False),
        sa.Column("reference_price", sa.Float()),
        sa.Column("expected_fill", sa.Float()),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("filled_at", sa.DateTime(timezone=True)),
        sa.Column("filled_qty", sa.Float(), nullable=False, server_default="0"),
        sa.Column("avg_fill_price", sa.Float()),
        sa.Column("reject_code", sa.Text()),
        sa.Column("slippage_usd", sa.Float()),
        sa.Column("slippage_bps", sa.Float()),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
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
        sa.CheckConstraint("qty > 0", name="ck_order_intent_qty_positive"),
        sa.CheckConstraint("filled_qty >= 0", name="ck_order_intent_filled_qty_nonnegative"),
        sa.CheckConstraint("reserved_cash_usd >= 0", name="ck_order_intent_reserved_cash_nonnegative"),
        sa.CheckConstraint("reserved_margin_usd >= 0", name="ck_order_intent_reserved_margin_nonnegative"),
        sa.CheckConstraint("row_version >= 1", name="ck_order_intent_row_version_positive"),
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
        sa.Column("closed_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gross_pnl_usd", sa.Float(), nullable=False),
        sa.Column("net_pnl_usd", sa.Float(), nullable=False),
        sa.Column("total_cost_usd", sa.Float(), nullable=False),
        sa.Column("mfe_usd", sa.Float()),
        sa.Column("mae_usd", sa.Float()),
        sa.Column("capture_efficiency", sa.Float()),
        sa.Column("duration_s", sa.Float(), nullable=False),
        sa.Column("exit_reason", sa.Text(), nullable=False),
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
        sa.CheckConstraint("total_cost_usd >= 0", name="ck_closed_trade_cost_nonnegative"),
        sa.CheckConstraint("duration_s >= 0", name="ck_closed_trade_duration_nonnegative"),
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
        sa.Column("evidence_id", sa.Text()),
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
