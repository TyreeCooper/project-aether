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

from aether_vnext.schema import build_metadata


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

    # EventLedger is append-only Firm evidence. Projection rebuilds may read it;
    # no application path may UPDATE or DELETE historical decisions.
    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION {SCHEMA}.reject_event_ledger_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'aether_vnext.event_ledger is append-only';
            END;
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            DROP TRIGGER IF EXISTS trg_event_ledger_append_only
            ON {SCHEMA}.event_ledger
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE TRIGGER trg_event_ledger_append_only
            BEFORE UPDATE OR DELETE ON {SCHEMA}.event_ledger
            FOR EACH ROW
            EXECUTE FUNCTION {SCHEMA}.reject_event_ledger_mutation()
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.execute(
        sa.text(
            f"""
            DROP TRIGGER IF EXISTS trg_event_ledger_append_only
            ON {SCHEMA}.event_ledger
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            DROP FUNCTION IF EXISTS {SCHEMA}.reject_event_ledger_mutation()
            """
        )
    )
    metadata = build_metadata(schema=SCHEMA)
    metadata.drop_all(bind=bind, checkfirst=True)
