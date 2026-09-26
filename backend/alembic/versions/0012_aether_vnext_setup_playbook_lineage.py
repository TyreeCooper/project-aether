"""Bind durable playbook identity to Scout Setup lineage.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


def upgrade() -> None:
    for table_name in ("decision_lineage",):
        op.add_column(
            table_name,
            sa.Column("playbook_id", sa.Text()),
            schema=SCHEMA,
        )
        op.add_column(
            table_name,
            sa.Column("playbook_version", sa.Text()),
            schema=SCHEMA,
        )
        op.add_column(
            table_name,
            sa.Column("risk_cluster_id", sa.Text()),
            schema=SCHEMA,
        )
        op.add_column(
            table_name,
            sa.Column("asset_risk_hitches", sa.JSON()),
            schema=SCHEMA,
        )

    op.add_column(
        "setups",
        sa.Column("playbook_id", sa.Text(), nullable=False),
        schema=SCHEMA,
    )
    op.add_column(
        "setups",
        sa.Column("playbook_version", sa.Text(), nullable=False),
        schema=SCHEMA,
    )
    op.add_column(
        "setups",
        sa.Column("risk_cluster_id", sa.Text(), nullable=False),
        schema=SCHEMA,
    )
    op.add_column(
        "setups",
        sa.Column("asset_risk_hitches", sa.JSON(), nullable=False),
        schema=SCHEMA,
    )
    op.add_column(
        "setups",
        sa.Column(
            "trigger_bar_close_exchange_ts",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "setups",
        sa.Column(
            "exit_contract_complete",
            sa.Boolean(),
            nullable=False,
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "setups",
        sa.Column("exit_contract_gap", sa.Text()),
        schema=SCHEMA,
    )
    op.create_unique_constraint(
        "uq_setup_playbook_closed_bar_once",
        "setups",
        [
            "playbook_id",
            "asset_id",
            "horizon",
            "side",
            "trigger_bar_close_exchange_ts",
        ],
        schema=SCHEMA,
    )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.reject_setup_playbook_identity_mutation()
        RETURNS trigger AS $aether$
        BEGIN
            IF OLD.playbook_id IS DISTINCT FROM NEW.playbook_id
               OR OLD.playbook_version IS DISTINCT FROM NEW.playbook_version
               OR OLD.risk_cluster_id IS DISTINCT FROM NEW.risk_cluster_id
               OR OLD.asset_risk_hitches IS DISTINCT FROM NEW.asset_risk_hitches
               OR OLD.trigger_bar_close_exchange_ts IS DISTINCT FROM NEW.trigger_bar_close_exchange_ts
               OR OLD.exit_contract_complete IS DISTINCT FROM NEW.exit_contract_complete
               OR OLD.exit_contract_gap IS DISTINCT FROM NEW.exit_contract_gap
            THEN
                RAISE EXCEPTION 'Scout Setup playbook identity is immutable';
            END IF;
            RETURN NEW;
        END;
        $aether$ LANGUAGE plpgsql
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_setup_playbook_identity_immutable
        BEFORE UPDATE ON {SCHEMA}.setups
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.reject_setup_playbook_identity_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_setup_playbook_identity_immutable "
        f"ON {SCHEMA}.setups"
    )
    op.execute(
        f"DROP FUNCTION IF EXISTS "
        f"{SCHEMA}.reject_setup_playbook_identity_mutation()"
    )
    op.drop_constraint(
        "uq_setup_playbook_closed_bar_once",
        "setups",
        type_="unique",
        schema=SCHEMA,
    )
    for column_name in (
        "exit_contract_gap",
        "exit_contract_complete",
        "trigger_bar_close_exchange_ts",
        "asset_risk_hitches",
        "risk_cluster_id",
        "playbook_version",
        "playbook_id",
    ):
        op.drop_column("setups", column_name, schema=SCHEMA)
    for column_name in (
        "asset_risk_hitches",
        "risk_cluster_id",
        "playbook_version",
        "playbook_id",
    ):
        op.drop_column("decision_lineage", column_name, schema=SCHEMA)
