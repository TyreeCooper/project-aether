"""Persist immutable equity shortability/locate evidence.

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


def upgrade() -> None:
    op.create_table(
        "shortability_evidence",
        sa.Column("evidence_id", sa.Text(), primary_key=True),
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column(
            "configuration_hash",
            sa.Text(),
            sa.ForeignKey(f"{SCHEMA}.policy_snapshots.configuration_hash"),
            nullable=False,
        ),
        sa.Column("runtime_registry_binding_hash", sa.Text(), nullable=False),
        sa.Column("provider_id", sa.Text(), nullable=False),
        sa.Column("market_data_contract_id", sa.BigInteger(), nullable=False),
        sa.Column("shortable_shares", sa.Float(), nullable=False),
        sa.Column("fee_rate_raw", sa.Text()),
        sa.Column("shortable_raw", sa.Text()),
        sa.Column("market_data_availability", sa.Text(), nullable=False),
        sa.Column("provider_updated_at_utc", sa.DateTime(timezone=True)),
        sa.Column("received_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("adapter_version", sa.Text(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "market_data_contract_id > 0",
            name="ck_shortability_contract_id_positive",
        ),
        sa.CheckConstraint(
            "shortable_shares >= 0",
            name="ck_shortability_shares_nonnegative",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_shortability_evidence_asset_id",
        "shortability_evidence",
        ["asset_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_shortability_evidence_configuration_hash",
        "shortability_evidence",
        ["configuration_hash"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_shortability_evidence_received_at_utc",
        "shortability_evidence",
        ["received_at_utc"],
        schema=SCHEMA,
    )
    op.add_column(
        "order_intents",
        sa.Column("shortability_evidence_id", sa.Text()),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_order_intents_shortability_evidence_id",
        "order_intents",
        "shortability_evidence",
        ["shortability_evidence_id"],
        ["evidence_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
    )

    op.execute(
        f"""
        CREATE TRIGGER trg_shortability_evidence_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.shortability_evidence
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.reject_immutable_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_shortability_evidence_immutable "
        f"ON {SCHEMA}.shortability_evidence"
    )
    op.drop_constraint(
        "fk_order_intents_shortability_evidence_id",
        "order_intents",
        type_="foreignkey",
        schema=SCHEMA,
    )
    op.drop_column(
        "order_intents",
        "shortability_evidence_id",
        schema=SCHEMA,
    )
    for index in (
        "ix_shortability_evidence_received_at_utc",
        "ix_shortability_evidence_configuration_hash",
        "ix_shortability_evidence_asset_id",
    ):
        op.drop_index(
            index,
            table_name="shortability_evidence",
            schema=SCHEMA,
        )
    op.drop_table("shortability_evidence", schema=SCHEMA)
