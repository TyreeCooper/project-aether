"""Persistence namespace contract for AETHER vNext.

No legacy table name is accepted here. vNext persistence is physically namespaced
under PostgreSQL schema `aether_vnext` so legacy state cannot become vNext state
by accident.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from aether_vnext.freeze import CONFIGURATION_HASH, FREEZE_VERSION, SPEC_BUNDLE


DB_SCHEMA: Final = "aether_vnext"
NAMESPACE_VERSION: Final = 1
RUNTIME_MANIFEST_TABLE: Final = "runtime_manifest"


def qualified_table(table: str) -> str:
    name = str(table).strip()
    if not name or not name.replace("_", "").isalnum():
        raise ValueError(f"invalid vNext table name: {table!r}")
    return f"{DB_SCHEMA}.{name}"


@dataclass(frozen=True, slots=True)
class RuntimeManifest:
    manifest_id: str
    freeze_version: str
    spec_bundle: str
    configuration_hash: str
    namespace_version: int
    paper_only: bool
    live_blocked: bool


def canonical_runtime_manifest() -> RuntimeManifest:
    return RuntimeManifest(
        manifest_id=f"{FREEZE_VERSION}:{CONFIGURATION_HASH[:16]}",
        freeze_version=FREEZE_VERSION,
        spec_bundle=SPEC_BUNDLE,
        configuration_hash=CONFIGURATION_HASH,
        namespace_version=NAMESPACE_VERSION,
        paper_only=True,
        live_blocked=True,
    )
