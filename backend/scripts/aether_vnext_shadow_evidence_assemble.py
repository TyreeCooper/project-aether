"""Assemble canonical Phase-17 runtime-shadow evidence from observed artifacts.

This command performs no network access and no runtime mutation. It combines a
deployed HTTP probe artifact with a separate process-level observation artifact.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from aether_vnext.shadow_evidence_assembly import (
    RuntimeProcessObservation,
    assemble_runtime_shadow_evidence,
)


def _load_mapping(path: str, *, name: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{name} must contain a JSON object")
    return payload


def _datetime(value: object, *, name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be an ISO-8601 timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed


def assemble_from_payloads(
    *,
    http_probe: dict[str, Any],
    process_payload: dict[str, Any],
    evidence_id: str,
    deployed_revision: str,
    http_probe_artifact_id: str,
) -> dict[str, object]:
    process = RuntimeProcessObservation(
        observation_id=process_payload["observation_id"],
        deployed_revision=process_payload["deployed_revision"],
        observed_at_utc=_datetime(
            process_payload["observed_at_utc"],
            name="process_observation.observed_at_utc",
        ),
        second_runtime_started=bool(
            process_payload["second_runtime_started"]
        ),
        source_artifact_ids=tuple(
            str(value) for value in process_payload["source_artifact_ids"]
        ),
        synthetic=bool(process_payload.get("synthetic", False)),
    )
    evidence = assemble_runtime_shadow_evidence(
        evidence_id=evidence_id,
        deployed_revision=deployed_revision,
        http_probe=http_probe,
        http_probe_artifact_id=http_probe_artifact_id,
        process_observation=process,
    )
    return {
        "evidence_id": evidence.evidence_id,
        "environment": evidence.environment,
        "deployed_revision": evidence.deployed_revision,
        "observed_at_utc": evidence.observed_at_utc.isoformat(),
        "floor_route_status_code": evidence.floor_route_status_code,
        "dedicated_vnext_book_read": evidence.dedicated_vnext_book_read,
        "legacy_surface_available": evidence.legacy_surface_available,
        "mutation_transport_absent": evidence.mutation_transport_absent,
        "second_runtime_started": evidence.second_runtime_started,
        "paper_only": evidence.paper_only,
        "live_blocked": evidence.live_blocked,
        "source_artifact_ids": list(evidence.source_artifact_ids),
        "synthetic": evidence.synthetic,
        "verified": evidence.verified,
        "assembler_authority": {
            "read_only": True,
            "network_access": False,
            "runtime_mutation": False,
            "live_execution_authorized": False,
        },
    }


def _main(
    *,
    http_probe_path: str,
    process_observation_path: str,
    evidence_id: str,
    deployed_revision: str,
    http_probe_artifact_id: str,
    output_path: str | None,
) -> int:
    payload = assemble_from_payloads(
        http_probe=_load_mapping(
            http_probe_path,
            name="HTTP probe artifact",
        ),
        process_payload=_load_mapping(
            process_observation_path,
            name="process observation artifact",
        ),
        evidence_id=evidence_id,
        deployed_revision=deployed_revision,
        http_probe_artifact_id=http_probe_artifact_id,
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
    parser.add_argument("--http-probe", required=True)
    parser.add_argument("--process-observation", required=True)
    parser.add_argument("--evidence-id", required=True)
    parser.add_argument("--deployed-revision", required=True)
    parser.add_argument("--http-probe-artifact-id", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    raise SystemExit(
        _main(
            http_probe_path=args.http_probe,
            process_observation_path=args.process_observation,
            evidence_id=args.evidence_id,
            deployed_revision=args.deployed_revision,
            http_probe_artifact_id=args.http_probe_artifact_id,
            output_path=args.output,
        )
    )
