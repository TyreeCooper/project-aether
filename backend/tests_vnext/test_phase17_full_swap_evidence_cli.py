from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path

import pytest


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 19, 30, tzinfo=UTC)
REV = "1234567890abcdef1234567890abcdef12345678"


def _load_script():
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "aether_vnext_full_swap_evidence.py"
    )
    spec = importlib.util.spec_from_file_location("full_swap_evidence_cli", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bundle() -> dict:
    return {
        "assessment_id": "phase17-runtime-bundle",
        "assessed_at_utc": T0.isoformat(),
        "phase16_internal_closeout_green": True,
        "vnext_ci_green": True,
        "repository_ci_green": True,
        "legacy_runtime_authority_retirable": True,
        "paper_only": True,
        "live_blocked": True,
        "shadow": {
            "evidence_id": "shadow-1",
            "environment": "aether-vnext-burnin",
            "deployed_revision": REV,
            "observed_at_utc": T0.isoformat(),
            "floor_route_status_code": 200,
            "dedicated_vnext_book_read": True,
            "legacy_surface_available": True,
            "mutation_transport_absent": True,
            "second_runtime_started": False,
            "paper_only": True,
            "live_blocked": True,
            "source_artifact_ids": ["shadow-workflow-run-1"],
            "synthetic": False,
        },
        "restart_scenarios": [
            {
                "scenario_id": f"restart-{scenario}",
                "scenario": scenario,
                "deployed_revision": REV,
                "observed_at_utc": T0.isoformat(),
                "identity_preserved": True,
                "cash_preserved": True,
                "margin_preserved": True,
                "position_state_preserved": True,
                "idempotency_preserved": True,
                "reconciliation_clean": True,
                "source_artifact_ids": [f"restart-run-{scenario}"],
                "synthetic": False,
            }
            for scenario in ("mid_ticket", "mid_order", "open_trade")
        ],
        "rollback": {
            "evidence_id": "rollback-1",
            "deployed_revision": REV,
            "observed_at_utc": T0.isoformat(),
            "previous_paper_runtime_restored": True,
            "recovery_started_offline": True,
            "reconciliation_clean_before_arm": True,
            "automatic_rearm_observed": False,
            "operator_confirmation_required": True,
            "paper_only": True,
            "live_blocked": True,
            "source_artifact_ids": ["rollback-run-1"],
            "synthetic": False,
        },
        "book_reconciliation": {
            "evidence_id": "book-1",
            "deployed_revision": REV,
            "observed_at_utc": T0.isoformat(),
            "risk_admission_issues": [],
            "stale_order_intent_ids": [],
            "active_position_trade_identity_consistent": True,
            "broker_ledger_balanced": True,
            "source_artifact_ids": ["book-health-run-1"],
            "synthetic": False,
        },
    }


def test_validator_projects_complete_bundle_without_runtime_authority() -> None:
    module = _load_script()
    report = module.validate_bundle(_bundle())

    assert report["swap_ready"] is True
    assert report["activation_evidence_complete"] is True
    assert report["book_reconciliation_verified"] is True
    assert report["live_execution_authorized"] is False
    assert report["validator_authority"] == {
        "read_only": True,
        "may_switch_runtime": False,
        "may_start_runtime": False,
        "may_arm_runtime": False,
        "may_enable_live": False,
    }


def test_validator_surfaces_book_blocker_instead_of_coercing_green() -> None:
    module = _load_script()
    bundle = _bundle()
    bundle["book_reconciliation"]["stale_order_intent_ids"] = ["intent-1"]

    report = module.validate_bundle(bundle)

    assert report["swap_ready"] is False
    assert report["book_reconciliation_verified"] is False
    assert report["blocking_reasons"] == [
        "canonical_vnext_book_reconciled"
    ]


def test_validator_rejects_synthetic_runtime_evidence() -> None:
    module = _load_script()
    bundle = _bundle()
    bundle["shadow"]["synthetic"] = True

    with pytest.raises(ValueError, match="synthetic runtime-shadow evidence"):
        module.validate_bundle(bundle)
