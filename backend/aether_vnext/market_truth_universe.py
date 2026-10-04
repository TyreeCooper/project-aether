"""Layer 1: canonical AETHER Asset Universe.

The universe contains instrument identity only. It has no market-data, provider,
routing, fee, strategy, or execution authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable


@dataclass(frozen=True, slots=True)
class AssetUniverseRow:
    canonical_instrument_id: str
    asset_class: str
    tick_size: float
    lot_size: float
    session_calendar: str

    def __post_init__(self) -> None:
        if not self.canonical_instrument_id.strip():
            raise ValueError("canonical_instrument_id is required")
        if not self.asset_class.strip():
            raise ValueError("asset_class is required")
        if not isfinite(self.tick_size) or self.tick_size <= 0:
            raise ValueError("tick_size must be positive and finite")
        if not isfinite(self.lot_size) or self.lot_size <= 0:
            raise ValueError("lot_size must be positive and finite")
        if not self.session_calendar.strip():
            raise ValueError("session_calendar is required")


class AssetUniverse:
    """Immutable-by-replacement identity registry."""

    def __init__(self, rows: Iterable[AssetUniverseRow] = ()) -> None:
        by_id: dict[str, AssetUniverseRow] = {}
        for row in rows:
            key = row.canonical_instrument_id.strip().lower()
            if key in by_id:
                raise ValueError(f"duplicate universe instrument: {key}")
            by_id[key] = row
        self._rows = by_id

    def get(self, canonical_instrument_id: str) -> AssetUniverseRow | None:
        return self._rows.get(str(canonical_instrument_id).strip().lower())

    def rows(self) -> tuple[AssetUniverseRow, ...]:
        return tuple(self._rows[key] for key in sorted(self._rows))

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._rows))
