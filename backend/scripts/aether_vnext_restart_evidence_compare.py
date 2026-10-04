"""Compare deployed restart snapshots into canonical Phase-17 evidence."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from aether_vnext.restart_evidence_compare import (
    compare_restart_evidence_snapshots,
)
from aether_vnext.restart_evidence_snapshot import RestartEvidenceSnapshot


def _load_mapping(path: str, *, name: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{name} must contain a JSON object")
    return payload


def _snapshot(payload: dict[str, Any], *, name: str) -> RestartEvidenceSnapshot:
    observed = datetime.fromisoformat(str(payload["observed_at_utc"]))
    if observed.tzinfo is None:
        raise ValueError(f"{name}.observed_at_utc must be timezone-aware")
    state_payload = payload["state_payload"]
    if not isinstance(state_payload, dict):
        raise ValueError(f"{name}.state_payload must be a JSON object")
    blockers = payload["reconciliation_blockers"]
    source_ids = payload["source_artifact_ids"]
    if not isinstance(blockers, list):
        raise ValueError(f"{name}.reconciliation_blockers must be a JSON array")
    if not isinstance(source_ids, list):
        raise ValueError(f"{name}.source_artifact_ids must be a JSON array")
    return RestartEvidenceSnapshot(
        snapshot_id=str(payload["snapshot_id"]),
        deployed_revision=str(payload["deployed_revision"]),
        scenario=str(payload["scenario"]),
        observed_at_utc=observed,
        state_payload=state_payload,
        state_payload_hash=str(payload["state_payload_hash"]),
        reconciliation_blockers=tuple(str(value) for value in blockers),
        source_artifact_ids=tuple(str(value) for value in source_ids),
        synthetic=bool(payload.get("synthetic", False)),
    )


def compare_payloads(
    *,
    scenario_id: str,
    before_payload: dict[str, Any],
    after_payload: dict[str, Any],
) -> dict[str, object]:
    comparison = compare_restart_evidence_snapshots(
        scenario_id=scenario_id,
        before=_snapshot(before_payload, name="before"),
        after=_snapshot(after_payload, name="after"),
    )
    evidence = comparison.evidence
    return {
        "scenario_id": evidence.scenario_id,
        "scenario": evidence.scenario,
        "deployed_revision": evidence.deployed_revision,
        "observed_at_utc": evidence.observed_at_utc.isoformat(),
        "identity_preserved": evidence.identity_preserved,
        "cash_preserved": evidence.cash_preserved,
        "margin_preserved": evidence.margin_preserved,
        "position_state_preserved": evidence.position_state_preserved,
        "idempotency_preserved": evidence.idempotency_preserved,
        "reconciliation_clean": evidence.reconciliation_clean,
        "event_count_preserved": comparison.event_count_preserved,
        "before_state_payload_hash": comparison.before_state_payload_hash,
        "after_state_payload_hash": comparison.after_state_payload_hash,
        "source_artifact_ids": list(evidence.source_artifact_ids),
        "synthetic": False,
        "verified": evidence.verified,
        "comparator_authority": {
            "read_only": True,
            "runtime_mutation": False,
            "restart_authority": False,
            "live_execution_authorized": False,
        },
    }


def _main(
    *,
    scenario_id: str,
    before_path: str,
    after_path: str,
    output_path: str | None,
) -> int:
    payload = compare_payloads(
        scenario_id=scenario_id,
        before_payload=_load_mapping(before_path, name="before snapshot"),
        after_payload=_load_mapping(after_path, name="after snapshot"),
    )
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    print(rendered)
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    return 0 if payload["verified"] is True else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario-id", required=True)
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    raise SystemExit(
        _main(
            scenario_id=args.scenario_id,
            before_path=args.before,
            after_path=args.after,
            output_path=args.output,
        )
    )
