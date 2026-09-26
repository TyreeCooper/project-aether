"""Current AETHER vNext SQLAlchemy metadata facade.

Revision-specific migrations must import their frozen schema module directly.
Runtime code may import this facade, which can evolve only through a new migration.
"""
from __future__ import annotations

from aether_vnext.schema_v0004 import METADATA, build_metadata

__all__ = ["METADATA", "build_metadata"]
