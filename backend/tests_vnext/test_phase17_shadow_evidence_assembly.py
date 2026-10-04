from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.shadow_evidence_assembly import (
    RuntimeProcessObservation,
    assemble_runtime_shadow_evidence,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 29, 19, 15, tzinfo=UTC)
REV = "abcdef1234567890abcdef1234567890abcdef12"


def _probe(**overrides) -> dict:
    payload = {
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
    payload.update(overrides)
    return payload


def _process(**overrides) -> RuntimeProcessObservation:
    values = {
        "observation_id": "process-1",
        "deployed_revision": REV,
        "observed_at_utc": T0 + timedelta(seconds=5),
        "second_runtime_started": False,
        "source_artifact_ids": ("process-observation-1",),
        "synthetic": False,
    }
    values.update(overrides)
    return RuntimeProcessObservation(**values)


def test_assembler_requires_http_and_process_evidence_before_canonical_shadow_record() -> None:
    evidence = assemble_runtime_shadow_evidence(
        evidence_id="shadow-combined-1",
        deployed_revision=REV,
        http_probe=_probe(),
        http_probe_artifact_id="shadow-http-run-1",
        process_observation=_process(),
    )

    assert evidence.verified is True
    assert evidence.dedicated_vnext_book_read is True
    assert evidence.legacy_surface_available is True
    assert evidence.mutation_transport_absent is True
    assert evidence.second_runtime_started is False
    assert evidence.paper_only is True
    assert evidence.live_blocked is True
    assert evidence.source_artifact_ids == (
        "shadow-http-run-1",
        "process-observation-1",
    )
    assert evidence.observed_at_utc == T0 + timedelta(seconds=5)


def test_process_observation_of_second_runtime_keeps_canonical_evidence_unverified() -> None:
    evidence = assemble_runtime_shadow_evidence(
        evidence_id="shadow-combined-2",
        deployed_revision=REV,
        http_probe=_probe(),
        http_probe_artifact_id="shadow-http-run-2",
        process_observation=_process(second_runtime_started=True),
    )

    assert evidence.second_runtime_started is True
    assert evidence.verified is False


def test_unverified_http_probe_cannot_be_promoted_to_runtime_shadow_evidence() -> None:
    with pytest.raises(ValueError, match="HTTP shadow probe must be verified"):
        assemble_runtime_shadow_evidence(
            evidence_id="shadow-bad-http",
            deployed_revision=REV,
            http_probe=_probe(http_shadow_verified=False),
            http_probe_artifact_id="shadow-http-run-bad",
            process_observation=_process(),
        )


def test_http_and_process_evidence_must_share_revision() -> None:
    with pytest.raises(ValueError, match="share deployed revision"):
        assemble_runtime_shadow_evidence(
            evidence_id="shadow-revision-mismatch",
            deployed_revision=REV,
            http_probe=_probe(),
            http_probe_artifact_id="shadow-http-run-3",
            process_observation=_process(deployed_revision="different"),
        )


def test_synthetic_process_observation_is_rejected() -> None:
    with pytest.raises(ValueError, match="synthetic process observation"):
        _process(synthetic=True)
