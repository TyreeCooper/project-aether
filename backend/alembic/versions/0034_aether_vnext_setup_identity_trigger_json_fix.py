"""Fix PostgreSQL JSON comparison in Setup identity immutability trigger.

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-01
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "aether_vnext"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.reject_setup_playbook_identity_mutation()
        RETURNS trigger AS $aether$
        BEGIN
            IF OLD.playbook_id IS DISTINCT FROM NEW.playbook_id
               OR OLD.playbook_version IS DISTINCT FROM NEW.playbook_version
               OR OLD.risk_cluster_id IS DISTINCT FROM NEW.risk_cluster_id
               OR to_jsonb(OLD.asset_risk_hitches)
                  IS DISTINCT FROM to_jsonb(NEW.asset_risk_hitches)
               OR OLD.trigger_bar_close_exchange_ts
                  IS DISTINCT FROM NEW.trigger_bar_close_exchange_ts
               OR OLD.exit_contract_complete
                  IS DISTINCT FROM NEW.exit_contract_complete
               OR OLD.exit_contract_gap IS DISTINCT FROM NEW.exit_contract_gap
            THEN
                RAISE EXCEPTION 'Scout Setup playbook identity is immutable';
            END IF;
            RETURN NEW;
        END;
        $aether$ LANGUAGE plpgsql
        """
    )


def downgrade() -> None:
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
