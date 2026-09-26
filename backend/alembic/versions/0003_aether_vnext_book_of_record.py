"""Create AETHER vNext book of record and current-state projections.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-26

The migration is isolated to PostgreSQL schema `aether_vnext`. Legacy tables are
untouched. Seed paper ledgers are inserted once by migration, never by application
restart hooks.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from aether_vnext.schema_v0003 import build_metadata


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


def upgrade() -> None:
    bind = op.get_bind()
    metadata = build_metadata(schema=SCHEMA)
    metadata.create_all(bind=bind, checkfirst=True)

    # Seed $10k across four broker-local paper ledgers exactly once. Alembic
    # migrations do not rerun on process restart; ON CONFLICT protects manual
    # re-execution without minting capital.
    op.execute(
        sa.text(
            f"""
            INSERT INTO {SCHEMA}.broker_account_ledgers
                (
                    broker_account_id,
                    cash_available_usd,
                    cash_reserved_usd,
                    margin_used_usd,
                    margin_available_usd,
                    realized_pnl_usd,
                    unrealized_pnl_usd,
                    fees_accrued_usd,
                    settled_cash_usd,
                    reconciliation_state,
                    row_version
                )
            VALUES
                ('kraken_paper', 4000, 0, 0, 4000, 0, 0, 0, 4000, 'clean', 1),
                ('tastyfx_paper', 2000, 0, 0, 2000, 0, 0, 0, 2000, 'clean', 1),
                ('ninja_paper', 2000, 0, 0, 2000, 0, 0, 0, 2000, 'clean', 1),
                ('ibkr_paper', 2000, 0, 0, 2000, 0, 0, 0, 2000, 'clean', 1)
            ON CONFLICT (broker_account_id) DO NOTHING
            """
        )
    )

    # Immutable Firm evidence/history. EventLedger is append-only; policy
    # snapshots and ExitPlans are versioned rather than edited; consumed signals
    # and ClosedTrades must never be rewritten to make later evidence look better.
    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION {SCHEMA}.reject_immutable_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $aether$
            BEGIN
                RAISE EXCEPTION 'AETHER vNext immutable record cannot be updated or deleted';
            END;
            $aether$;
            """
        )
    )
    immutable_tables = (
        ("event_ledger", "trg_event_ledger_append_only"),
        ("policy_snapshots", "trg_policy_snapshots_immutable"),
        ("exit_plans", "trg_exit_plans_immutable"),
        ("closed_trades", "trg_closed_trades_immutable"),
        ("signal_consumptions", "trg_signal_consumptions_immutable"),
    )
    for table_name, trigger_name in immutable_tables:
        op.execute(
            sa.text(
                f"""
                DROP TRIGGER IF EXISTS {trigger_name}
                ON {SCHEMA}.{table_name}
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER {trigger_name}
                BEFORE UPDATE OR DELETE ON {SCHEMA}.{table_name}
                FOR EACH ROW
                EXECUTE FUNCTION {SCHEMA}.reject_immutable_mutation()
                """
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    immutable_tables = (
        ("event_ledger", "trg_event_ledger_append_only"),
        ("policy_snapshots", "trg_policy_snapshots_immutable"),
        ("exit_plans", "trg_exit_plans_immutable"),
        ("closed_trades", "trg_closed_trades_immutable"),
        ("signal_consumptions", "trg_signal_consumptions_immutable"),
    )
    for table_name, trigger_name in immutable_tables:
        op.execute(
            sa.text(
                f"""
                DROP TRIGGER IF EXISTS {trigger_name}
                ON {SCHEMA}.{table_name}
                """
            )
        )
    op.execute(
        sa.text(
            f"""
            DROP FUNCTION IF EXISTS {SCHEMA}.reject_immutable_mutation()
            """
        )
    )
    metadata = build_metadata(schema=SCHEMA)
    metadata.drop_all(bind=bind, checkfirst=True)
