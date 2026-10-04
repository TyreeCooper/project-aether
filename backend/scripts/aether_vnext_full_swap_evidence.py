"""Validate externally observed Phase-17 runtime evidence.

This command is read-only. It reads a JSON evidence bundle, applies the canonical
Phase-17 evidence contracts, and emits a readiness report. It does not connect to a
broker/database, switch runtimes, deploy code, or authorize live execution.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from aether_vnext.full_swap_evidence_readiness import (
    BookReconciliationEvidence,
    FullSwapEvidenceBoundInput,
    assess_evidence_bound_full_swap_readiness,
)
from aether_vnext.full_swap_runtime_evidence import (
    RestartScenarioEvidence,
    RollbackRuntimeEvidence,
    RuntimeShadowEvidence,
    assess_phase17_runtime_evidence,
)


def _dt(value: object, *, name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be an ISO-8601 timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed


def _tuple_text(value: object, *, name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a JSON array")
    return tuple(str(item) for item in value)


def _require_mapping(value: object, *, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _shadow(raw: dict[str, Any]) -> RuntimeShadowEvidence:
    return RuntimeShadowEvidence(
        evidence_id=raw["evidence_id"],
        environment=raw["environment"],
        deployed_revision=raw["deployed_revision"],
        observed_at_utc=_dt(raw["observed_at_utc"], name="shadow.observed_at_utc"),
        floor_route_status_code=int(raw["floor_route_status_code"]),
        dedicated_vnext_book_read=bool(raw["dedicated_vnext_book_read"]),
        legacy_surface_available=bool(raw["legacy_surface_available"]),
        mutation_transport_absent=bool(raw["mutation_transport_absent"]),
        second_runtime_started=bool(raw["second_runtime_started"]),
        paper_only=bool(raw["paper_only"]),
        live_blocked=bool(raw["live_blocked"]),
        source_artifact_ids=_tuple_text(
            raw["source_artifact_ids"],
            name="shadow.source_artifact_ids",
        ),
        synthetic=bool(raw.get("synthetic", False)),
    )


def _restart(raw: dict[str, Any]) -> RestartScenarioEvidence:
    return RestartScenarioEvidence(
        scenario_id=raw["scenario_id"],
        scenario=raw["scenario"],
        deployed_revision=raw["deployed_revision"],
        observed_at_utc=_dt(
            raw["observed_at_utc"],
            name=f"restart[{raw.get('scenario', '?')}].observed_at_utc",
        ),
        identity_preserved=bool(raw["identity_preserved"]),
        cash_preserved=bool(raw["cash_preserved"]),
        margin_preserved=bool(raw["margin_preserved"]),
        position_state_preserved=bool(raw["position_state_preserved"]),
        idempotency_preserved=bool(raw["idempotency_preserved"]),
        reconciliation_clean=bool(raw["reconciliation_clean"]),
        source_artifact_ids=_tuple_text(
            raw["source_artifact_ids"],
            name="restart.source_artifact_ids",
        ),
        synthetic=bool(raw.get("synthetic", False)),
    )


def _rollback(raw: dict[str, Any]) -> RollbackRuntimeEvidence:
    return RollbackRuntimeEvidence(
        evidence_id=raw["evidence_id"],
        deployed_revision=raw["deployed_revision"],
        observed_at_utc=_dt(
            raw["observed_at_utc"],
            name="rollback.observed_at_utc",
        ),
        previous_paper_runtime_restored=bool(
            raw["previous_paper_runtime_restored"]
        ),
        recovery_started_offline=bool(raw["recovery_started_offline"]),
        reconciliation_clean_before_arm=bool(
            raw["reconciliation_clean_before_arm"]
        ),
        automatic_rearm_observed=bool(raw["automatic_rearm_observed"]),
        operator_confirmation_required=bool(
            raw["operator_confirmation_required"]
        ),
        paper_only=bool(raw["paper_only"]),
        live_blocked=bool(raw["live_blocked"]),
        source_artifact_ids=_tuple_text(
            raw["source_artifact_ids"],
            name="rollback.source_artifact_ids",
        ),
        synthetic=bool(raw.get("synthetic", False)),
    )


def _book(raw: dict[str, Any]) -> BookReconciliationEvidence:
    return BookReconciliationEvidence(
        evidence_id=raw["evidence_id"],
        deployed_revision=raw["deployed_revision"],
        observed_at_utc=_dt(
            raw["observed_at_utc"],
            name="book_reconciliation.observed_at_utc",
        ),
        risk_admission_issues=_tuple_text(
            raw["risk_admission_issues"],
            name="book_reconciliation.risk_admission_issues",
        ),
        stale_order_intent_ids=_tuple_text(
            raw["stale_order_intent_ids"],
            name="book_reconciliation.stale_order_intent_ids",
        ),
        active_position_trade_identity_consistent=bool(
            raw["active_position_trade_identity_consistent"]
        ),
        broker_ledger_balanced=bool(raw["broker_ledger_balanced"]),
        source_artifact_ids=_tuple_text(
            raw["source_artifact_ids"],
            name="book_reconciliation.source_artifact_ids",
        ),
        synthetic=bool(raw.get("synthetic", False)),
    )


def validate_bundle(payload: dict[str, Any]) -> dict[str, object]:
    shadow = _shadow(_require_mapping(payload["shadow"], name="shadow"))
    restart_raw = payload["restart_scenarios"]
    if not isinstance(restart_raw, list):
        raise ValueError("restart_scenarios must be a JSON array")
    restart = tuple(
        _restart(_require_mapping(row, name="restart scenario"))
        for row in restart_raw
    )
    rollback = _rollback(
        _require_mapping(payload["rollback"], name="rollback")
    )
    book = _book(
        _require_mapping(
            payload["book_reconciliation"],
            name="book_reconciliation",
        )
    )

    runtime = assess_phase17_runtime_evidence(
        shadow=shadow,
        restart_scenarios=restart,
        rollback=rollback,
    )
    readiness = assess_evidence_bound_full_swap_readiness(
        FullSwapEvidenceBoundInput(
            assessment_id=payload["assessment_id"],
            assessed_at_utc=_dt(
                payload["assessed_at_utc"],
                name="assessed_at_utc",
            ),
            runtime_evidence=runtime,
            book_reconciliation=book,
            phase16_internal_closeout_green=bool(
                payload["phase16_internal_closeout_green"]
            ),
            vnext_ci_green=bool(payload["vnext_ci_green"]),
            repository_ci_green=bool(payload["repository_ci_green"]),
            legacy_runtime_authority_retirable=bool(
                payload["legacy_runtime_authority_retirable"]
            ),
            paper_only=bool(payload["paper_only"]),
            live_blocked=bool(payload["live_blocked"]),
        )
    )

    return {
        "assessment_id": readiness.assessment_id,
        "assessed_at_utc": readiness.assessed_at_utc.isoformat(),
        "deployed_revision": runtime.deployed_revision,
        "runtime_shadow_verified": runtime.runtime_shadow_verified,
        "restart_recovery_verified": runtime.restart_recovery_verified,
        "rollback_verified": runtime.rollback_verified,
        "book_reconciliation_verified": book.verified,
        "activation_evidence_complete": runtime.activation_evidence_complete,
        "runtime_evidence_blockers": list(runtime.blocking_reasons),
        "swap_ready": readiness.swap_ready,
        "blocking_reasons": list(readiness.blocking_reasons),
        "live_execution_authorized": False,
        "validator_authority": {
            "read_only": True,
            "may_switch_runtime": False,
            "may_start_runtime": False,
            "may_arm_runtime": False,
            "may_enable_live": False,
        },
    }


def _main(*, input_path: str, output_path: str | None) -> int:
    payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("evidence bundle must be a JSON object")
    report = validate_bundle(payload)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["swap_ready"] is True else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    raise SystemExit(
        _main(input_path=args.input, output_path=args.output)
    )
