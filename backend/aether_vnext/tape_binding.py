"""Independent runtime bindings for the AETHER Consensus Tape.

Tape bindings answer "where does AETHER observe this market?" They deliberately do
not contain broker, account, fee, margin, order, or execution authority fields.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from aether_vnext.registry import ProductRegistryRow
from aether_vnext.tape import MAX_TAPE_SOURCES
from aether_vnext.tape_policy import TapeQuorumPolicy, tape_asset_class


@dataclass(frozen=True, slots=True)
class TapeSourceBinding:
    source_id: str
    venue: str
    source_symbol: str
    contract_id: str | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        for name in ("source_id", "venue", "source_symbol"):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValueError(f"{name} is required")
        if self.contract_id is not None and not str(self.contract_id).strip():
            raise ValueError("contract_id must be nonblank when present")


@dataclass(frozen=True, slots=True)
class TapeRuntimeBinding:
    asset_id: str
    sources: tuple[TapeSourceBinding, ...]
    policy: TapeQuorumPolicy

    def __post_init__(self) -> None:
        if self.asset_id != self.asset_id.strip().lower() or not self.asset_id:
            raise ValueError("asset_id must be canonical lowercase")
        if len(self.sources) > MAX_TAPE_SOURCES:
            raise ValueError("Tape binding exceeds five-source capacity")
        source_ids = [row.source_id for row in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Tape source bindings must be independent by source_id")

    @property
    def enabled_sources(self) -> tuple[TapeSourceBinding, ...]:
        return tuple(row for row in self.sources if row.enabled)

    @property
    def execution_provider(self) -> None:
        """Tape has no broker/execution ownership by design."""
        return None


def bind_tape_sources(
    product: ProductRegistryRow,
    sources: Sequence[TapeSourceBinding],
    *,
    policy: TapeQuorumPolicy,
) -> TapeRuntimeBinding:
    if policy.asset_class is not tape_asset_class(product.product_type):
        raise ValueError("Tape policy asset class does not match product")
    return TapeRuntimeBinding(
        asset_id=product.asset_id,
        sources=tuple(sources),
        policy=policy,
    )


def tape_binding_blockers(binding: TapeRuntimeBinding) -> tuple[str, ...]:
    blockers: list[str] = []
    enabled = binding.enabled_sources
    if len(enabled) < binding.policy.required_quorum:
        blockers.append("tape_source_quorum_binding_incomplete")
    if not binding.policy.operational:
        blockers.extend(binding.policy.missing_requirements)
    return tuple(dict.fromkeys(blockers))
