from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from aether_vnext.burnin import (
    BurnInReadinessInput,
    assess_profitability_readiness,
)
from aether_vnext.store import VNextStore


UTC = timezone.utc
T0 = datetime(2026, 9, 26, 23, 50, tzinfo=UTC)


def _input(**overrides) -> BurnInReadinessInput:
    values = dict(
        assessment_id="ready-1",
        readiness_policy_version="profitability-readiness-v1",
        firm_snapshot_hash="firm-snapshot-1",
        burn_in_start_at_utc=T0 - timedelta(days=30),
        burn_in_end_at_utc=T0,
        as_of_utc=T0,
        sustained_operation_satisfied=True,
        sustained_operation_policy_version="burnin-policy-v1",
        oos_trusted_sufficiency_satisfied=True,
        oos_trusted_sufficiency_policy_version="oos-sufficiency-v1",
        active_route_count=4,
        trusted_route_count=2,
        oos_positive_route_count=4,
        unresolved_accounting_defects=(),
        unresolved_model_defects=(),
        architecture_execution_green=True,
        versioned_net_cost_evidence_complete=True,
        held_out_positive_expectancy_complete=True,
        realistic_execution_complete=True,
        declared_regimes_complete=True,
        survivable_risk_complete=True,
        portfolio_constraints_complete=True,
        decay_bench_mechanism_operational=True,
        material_change_lineage_complete=True,
        full_history_retained=True,
        live_blocked=True,
    )
    values.update(overrides)
    return BurnInReadinessInput(**values)


def test_ready_requires_every_source_bound_evidence_condition() -> None:
    out = assess_profitability_readiness(_input())
    assert out.profitability_ready is True
    assert out.live_execution_authorized is False
    assert out.blocking_reasons == ()
    assert out.unresolved_rules == ()
    assert out.burn_in_duration_s == pytest.approx(30 * 24 * 3600)


def test_unbound_duration_and_oos_sufficiency_never_fake_readiness() -> None:
    out = assess_profitability_readiness(
        _input(
            sustained_operation_satisfied=None,
            sustained_operation_policy_version=None,
            oos_trusted_sufficiency_satisfied=None,
            oos_trusted_sufficiency_policy_version=None,
        )
    )
    assert out.profitability_ready is False
    assert set(out.unresolved_rules) == {
        "burn_in_duration_sufficiency_policy_unbound",
        "oos_trusted_route_sufficiency_policy_unbound",
    }
    assert out.live_execution_authorized is False


@pytest.mark.parametrize(
    "field,reason",
    (
        ("architecture_execution_green", "architecture_execution_green"),
        (
            "versioned_net_cost_evidence_complete",
            "versioned_net_cost_evidence_complete",
        ),
        (
            "held_out_positive_expectancy_complete",
            "held_out_positive_expectancy_complete",
        ),
        ("realistic_execution_complete", "realistic_execution_complete"),
        ("declared_regimes_complete", "declared_regimes_complete"),
        ("survivable_risk_complete", "survivable_risk_complete"),
        ("portfolio_constraints_complete", "portfolio_constraints_complete"),
        (
            "decay_bench_mechanism_operational",
            "decay_bench_mechanism_operational",
        ),
        (
            "material_change_lineage_complete",
            "material_change_lineage_complete",
        ),
        ("full_history_retained", "full_history_retained"),
        ("live_blocked", "live_blocked"),
    ),
)
def test_any_missing_final_profitability_condition_blocks_ready(
    field: str,
    reason: str,
) -> None:
    out = assess_profitability_readiness(_input(**{field: False}))
    assert out.profitability_ready is False
    assert reason in out.blocking_reasons
    assert out.live_execution_authorized is False


def test_unresolved_accounting_or_model_defect_blocks_ready() -> None:
    accounting = assess_profitability_readiness(
        _input(unresolved_accounting_defects=("ledger-drift",))
    )
    assert "unresolved_accounting_defects" in accounting.blocking_reasons

    model = assess_profitability_readiness(
        _input(unresolved_model_defects=("carry-engine-defect",))
    )
    assert "unresolved_model_defects" in model.blocking_reasons


def test_bound_sufficiency_decisions_require_versioned_policies() -> None:
    with pytest.raises(ValueError, match="sustained_operation_policy_version"):
        _input(sustained_operation_policy_version=None)
    with pytest.raises(ValueError, match="oos_trusted_sufficiency_policy_version"):
        _input(oos_trusted_sufficiency_policy_version=None)


def test_p11_assessment_persists_append_only_without_live_authority() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    assessment = assess_profitability_readiness(_input())
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        store.record_profitability_readiness_assessment(
            conn,
            assessment,
            created_at_utc=T0,
        )
        row = conn.execute(
            sa.select(
                store.tables["profitability_readiness_assessments"]
            )
        ).mappings().one()

    assert row["profitability_ready"] is True
    assert row["live_execution_authorized"] is False
    assert row["trusted_route_count"] == 2
    assert row["oos_positive_route_count"] == 4

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            store.record_profitability_readiness_assessment(
                conn,
                assessment,
                created_at_utc=T0,
            )
