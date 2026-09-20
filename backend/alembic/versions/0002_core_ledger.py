"""core durable ledger

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("client_order_id", sa.String(length=96), nullable=False, unique=True),
        sa.Column("venue_order_id", sa.String(length=128), nullable=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("order_type", sa.String(length=24), nullable=False),
        sa.Column("qty", sa.Float(), nullable=False),
        sa.Column("reference_price", sa.Float(), nullable=True),
        sa.Column("limit_price", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("actor", sa.String(length=32), nullable=False),
        sa.Column("paper_mode", sa.Boolean(), nullable=False),
        sa.Column("correlation_id", sa.String(length=96), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_orders_created_at", "orders", ["created_at"])
    op.create_index("ix_orders_status", "orders", ["status"])

    op.create_table(
        "fills",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("client_order_id", sa.String(length=96), nullable=False),
        sa.Column("venue_fill_id", sa.String(length=128), nullable=True, unique=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("qty", sa.Float(), nullable=False),
        sa.Column("reference_price", sa.Float(), nullable=False),
        sa.Column("execution_price", sa.Float(), nullable=False),
        sa.Column("fee_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("spread_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("slippage_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("gross_pnl_usd", sa.Float(), nullable=True),
        sa.Column("net_pnl_usd", sa.Float(), nullable=True),
        sa.Column("paper_mode", sa.Boolean(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_fills_client_order_id", "fills", ["client_order_id"])
    op.create_index("ix_fills_occurred_at", "fills", ["occurred_at"])

    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=32), nullable=False, unique=True),
        sa.Column("qty_open", sa.Float(), nullable=False, server_default="0"),
        sa.Column("avg_entry", sa.Float(), nullable=False, server_default="0"),
        sa.Column("realized_session", sa.Float(), nullable=False, server_default="0"),
        sa.Column("daily_realized", sa.Float(), nullable=False, server_default="0"),
        sa.Column("peak_equity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "account_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("usd", sa.Float(), nullable=False),
        sa.Column("btc", sa.Float(), nullable=False),
        sa.Column("equity_usd", sa.Float(), nullable=False),
        sa.Column("mark", sa.Float(), nullable=True),
        sa.Column("open_pnl", sa.Float(), nullable=False, server_default="0"),
        sa.Column("realized_session", sa.Float(), nullable=False, server_default="0"),
        sa.Column("daily_realized", sa.Float(), nullable=False, server_default="0"),
        sa.Column("gross_realized", sa.Float(), nullable=False, server_default="0"),
        sa.Column("entry_fees_open", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_fees", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_spread_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_slippage_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("max_drawdown_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_account_snapshots_captured_at", "account_snapshots", ["captured_at"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ts_utc", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("actor", sa.String(length=32), nullable=False),
        sa.Column("component", sa.String(length=48), nullable=False),
        sa.Column("event", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=96), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_audit_events_ts_utc", "audit_events", ["ts_utc"])
    op.create_index("ix_audit_events_correlation_id", "audit_events", ["correlation_id"])
    op.create_index("ix_audit_events_event", "audit_events", ["event"])

    op.create_table(
        "strategy_configs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("config_hash", sa.String(length=128), nullable=False, unique=True),
        sa.Column("strategy_name", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "risk_configs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("config_hash", sa.String(length=128), nullable=False, unique=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "reconcile_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("local_btc", sa.Float(), nullable=False),
        sa.Column("venue_btc", sa.Float(), nullable=False),
        sa.Column("delta_btc", sa.Float(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("reconcile_events")
    op.drop_table("risk_configs")
    op.drop_table("strategy_configs")
    op.drop_index("ix_audit_events_event", table_name="audit_events")
    op.drop_index("ix_audit_events_correlation_id", table_name="audit_events")
    op.drop_index("ix_audit_events_ts_utc", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_account_snapshots_captured_at", table_name="account_snapshots")
    op.drop_table("account_snapshots")
    op.drop_table("positions")
    op.drop_index("ix_fills_occurred_at", table_name="fills")
    op.drop_index("ix_fills_client_order_id", table_name="fills")
    op.drop_table("fills")
    op.drop_index("ix_orders_status", table_name="orders")
    op.drop_index("ix_orders_created_at", table_name="orders")
    op.drop_table("orders")
