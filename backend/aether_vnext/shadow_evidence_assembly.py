"""Assemble HTTP and process observations into canonical runtime-shadow evidence."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from aether_vnext.full_swap_runtime_evidence import RuntimeShadowEvidence


def _canonical_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be canonical text")
    return value


def _aware(name: str, value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class RuntimeProcessObservation:
    observation_id: str
    deployed_revision: str
    observed_at_utc: datetime
    second_runtime_started: bool
    source_artifact_ids: tuple[str, ...]
    synthetic: bool = False

    def __post_init__(self) -> None:
        _canonical_text("observation_id", self.observation_id)
        _canonical_text("deployed_revision", self.deployed_revision)
        _aware("observed_at_utc", self.observed_at_utc)
        if not self.source_artifact_ids:
            raise ValueError("source_artifact_ids must not be empty")
        for source_id in self.source_artifact_ids:
            _canonical_text("source_artifact_id", source_id)
        if len(self.source_artifact_ids) != len(set(self.source_artifact_ids)):
            raise ValueError("source_artifact_ids cannot contain duplicates")
        if self.synthetic is not False:
            raise ValueError("synthetic process observation is not admissible")


def _probe_observed_at(probe: Mapping[str, Any]) -> datetime:
    value = probe.get("observed_at_utc")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("HTTP probe observed_at_utc is required")
    parsed = datetime.fromisoformat(value)
    return _aware("HTTP probe observed_at_utc", parsed)


def _nested_mapping(
    probe: Mapping[str, Any],
    name: str,
) -> Mapping[str, Any]:
    value = probe.get(name)
    if not isinstance(value, Mapping):
        raise ValueError(f"HTTP probe {name} must be a mapping")
    return value


def assemble_runtime_shadow_evidence(
    *,
    evidence_id: str,
    deployed_revision: str,
    http_probe: Mapping[str, Any],
    http_probe_artifact_id: str,
    process_observation: RuntimeProcessObservation,
) -> RuntimeShadowEvidence:
    """Combine independently observed HTTP/process evidence without weakening either."""
    _canonical_text("evidence_id", evidence_id)
    _canonical_text("deployed_revision", deployed_revision)
    _canonical_text("http_probe_artifact_id", http_probe_artifact_id)

    if process_observation.deployed_revision != deployed_revision:
        raise ValueError(
            "process observation and HTTP evidence must share deployed revision"
        )

    probe_time = _probe_observed_at(http_probe)
    legacy = _nested_mapping(http_probe, "legacy")
    floor = _nested_mapping(http_probe, "vnext_floor")

    if http_probe.get("http_shadow_verified") is not True:
        raise ValueError("HTTP shadow probe must be verified before assembly")
    if legacy.get("available") is not True:
        raise ValueError("legacy surface must remain available")
    if floor.get("available") is not True:
        raise ValueError("vNext Floor must be available")
    if floor.get("paper_only") is not True:
        raise ValueError("vNext Floor must remain paper_only")
    if floor.get("live_blocked") is not True:
        raise ValueError("vNext Floor must remain live_blocked")
    if http_probe.get("mutation_transport_absent") is not True:
        raise ValueError("vNext Floor mutation transport must be absent")

    source_ids = tuple(
        dict.fromkeys(
            (http_probe_artifact_id, *process_observation.source_artifact_ids)
        )
    )
    observed_at = max(probe_time, process_observation.observed_at_utc)

    return RuntimeShadowEvidence(
        evidence_id=evidence_id,
        environment="aether-vnext-burnin",
        deployed_revision=deployed_revision,
        observed_at_utc=observed_at,
        floor_route_status_code=int(floor.get("status_code", 0)),
        dedicated_vnext_book_read=True,
        legacy_surface_available=True,
        mutation_transport_absent=True,
        second_runtime_started=process_observation.second_runtime_started,
        paper_only=True,
        live_blocked=True,
        source_artifact_ids=source_ids,
        synthetic=False,
    )
