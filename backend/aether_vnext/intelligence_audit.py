"""Research-only intelligence shadow audit records for AETHER vNext.

These records support later component ablations. They are counterfactual
diagnostics only and can never create an order or enable intelligence trade
influence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


INTELLIGENCE_COMPONENTS = frozenset(
    {"macro", "news", "community", "cross_asset"}
)


def _canonical_text(name: str, value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise ValueError(f"{name} must be canonical text")
    return value


@dataclass(frozen=True, slots=True)
class IntelligenceShadowAudit:
    audit_id: str
    opportunity_id: str
    route_id: str
    as_of_utc: datetime
    baseline_configuration_hash: str
    shadow_configuration_hash: str
    enabled_components: tuple[str, ...]
    baseline_outcome: str
    shadow_outcome: str
    evidence_ids: tuple[str, ...]
    research_only: bool = True
    order_created: bool = False
    trade_influence_enabled: bool = False

    def __post_init__(self) -> None:
        for name in (
            "audit_id",
            "opportunity_id",
            "route_id",
            "baseline_configuration_hash",
            "shadow_configuration_hash",
            "baseline_outcome",
            "shadow_outcome",
        ):
            _canonical_text(name, getattr(self, name))
        if self.as_of_utc.tzinfo is None:
            raise ValueError("as_of_utc must be timezone-aware")
        if (
            self.baseline_configuration_hash
            == self.shadow_configuration_hash
        ):
            raise ValueError(
                "shadow audit requires distinct configuration hashes"
            )
        if (
            not isinstance(self.enabled_components, tuple)
            or not self.enabled_components
        ):
            raise ValueError(
                "enabled_components must be a nonempty immutable tuple"
            )
        if len(set(self.enabled_components)) != len(self.enabled_components):
            raise ValueError("enabled_components must be unique")
        unknown = set(self.enabled_components) - INTELLIGENCE_COMPONENTS
        if unknown:
            raise ValueError(
                "enabled_components contain unknown intelligence components"
            )
        if tuple(sorted(self.enabled_components)) != self.enabled_components:
            raise ValueError("enabled_components must be canonical sorted order")
        if not isinstance(self.evidence_ids, tuple):
            raise ValueError("evidence_ids must be an immutable tuple")
        if any(
            not isinstance(value, str)
            or not value
            or value != value.strip()
            for value in self.evidence_ids
        ):
            raise ValueError("evidence_ids entries must be canonical text")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("evidence_ids must be unique")
        if self.research_only is not True:
            raise ValueError("intelligence shadow audit is research_only")
        if self.order_created is not False:
            raise ValueError("intelligence shadow audit cannot create orders")
        if self.trade_influence_enabled is not False:
            raise ValueError(
                "intelligence shadow audit cannot enable trade influence"
            )

    @property
    def outcome_changed(self) -> bool:
        return self.baseline_outcome != self.shadow_outcome


def summarize_shadow_audits(
    audits: tuple[IntelligenceShadowAudit, ...],
    *,
    enabled_components: tuple[str, ...],
) -> dict[str, object]:
    if not isinstance(audits, tuple):
        raise ValueError("audits must be an immutable tuple")
    if not isinstance(enabled_components, tuple) or not enabled_components:
        raise ValueError(
            "enabled_components must be a nonempty immutable tuple"
        )
    if tuple(sorted(enabled_components)) != enabled_components:
        raise ValueError("enabled_components must be canonical sorted order")
    if set(enabled_components) - INTELLIGENCE_COMPONENTS:
        raise ValueError("unknown intelligence component")
    rows = tuple(
        row for row in audits
        if row.enabled_components == enabled_components
    )
    return {
        "enabled_components": enabled_components,
        "observations": len(rows),
        "outcome_changed_count": sum(
            1 for row in rows if row.outcome_changed
        ),
        "outcome_unchanged_count": sum(
            1 for row in rows if not row.outcome_changed
        ),
        "alpha_claim": None,
        "trade_influence_enabled": False,
    }
