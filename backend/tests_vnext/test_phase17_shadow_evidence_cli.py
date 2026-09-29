from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path

import pytest


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 19, 30, tzinfo=UTC)
REV = "fedcba9876543210fedcba9876543210fedcba98"


def _load_script():
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "aether_vnext_shadow_evidence_assemble.py"
    )
    spec = importlib.util.spec_from_file_location("shadow_evidence_cli", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _probe() -> dict:
    return {
        "observed_at_utc": T0.isoformat(),
        "legacy": {
            "path": "/api/v1/health",
            "status_code": 200,
            "available": True,
        },
        "vnext_floor": {
            "path": "/api/v1/vnext/floor",
            "status_code": 200,
            "available": True,
            "paper_only": True,
            "live_blocked": True,
        },
        "mutation_transport_absent": True,
        "http_shadow_verified": True,
    }


def _process(**overrides) -> dict:
    payload = {
        "observation_id": "process-runtime-1",
        "deployed_revision": REV,
        "observed_at_utc": (T0 + timedelta(seconds=10)).isoformat(),
        "second_runtime_started": False,
        "source_artifact_ids": ["runtime-process-run-1"],
        "synthetic": False,
    }
    payload.update(overrides)
    return payload


def test_cli_assembly_emits_canonical_verified_shadow_evidence() -> None:
    module = _load_script()
    payload = module.assemble_from_payloads(
        http_probe=_probe(),
        process_payload=_process(),
        evidence_id="shadow-runtime-1",
        deployed_revision=REV,
        http_probe_artifact_id="shadow-http-run-1",
    )

    assert payload["verified"] is True
    assert payload["environment"] == "aether-vnext-burnin"
    assert payload["deployed_revision"] == REV
    assert payload["source_artifact_ids"] == [
        "shadow-http-run-1",
        "runtime-process-run-1",
    ]
    assert payload["assembler_authority"] == {
        "read_only": True,
        "network_access": False,
        "runtime_mutation": False,
        "live_execution_authorized": False,
    }


def test_cli_assembly_surfaces_second_runtime_as_unverified() -> None:
    module = _load_script()
    payload = module.assemble_from_payloads(
        http_probe=_probe(),
        process_payload=_process(second_runtime_started=True),
        evidence_id="shadow-runtime-2",
        deployed_revision=REV,
        http_probe_artifact_id="shadow-http-run-2",
    )

    assert payload["second_runtime_started"] is True
    assert payload["verified"] is False


def test_cli_assembly_rejects_revision_mismatch() -> None:
    module = _load_script()
    with pytest.raises(ValueError, match="share deployed revision"):
        module.assemble_from_payloads(
            http_probe=_probe(),
            process_payload=_process(deployed_revision="different"),
            evidence_id="shadow-runtime-3",
            deployed_revision=REV,
            http_probe_artifact_id="shadow-http-run-3",
        )


def test_cli_assembly_rejects_synthetic_process_observation() -> None:
    module = _load_script()
    with pytest.raises(ValueError, match="synthetic process observation"):
        module.assemble_from_payloads(
            http_probe=_probe(),
            process_payload=_process(synthetic=True),
            evidence_id="shadow-runtime-4",
            deployed_revision=REV,
            http_probe_artifact_id="shadow-http-run-4",
        )
