"""Layer 2: canonical AETHER Provider Cards.

Observation and execution are distinct provider capabilities. Fees and entitlements
exist only on Provider Cards; the Asset Universe must never carry them.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from aether_vnext.market_truth_contract import ProviderRole


@dataclass(frozen=True, slots=True)
class ProviderFeeSchedule:
    schedule_id: str
    maker_bps: float | None = None
    taker_bps: float | None = None
    commission_per_unit_usd: float | None = None
    regulatory_fee_model_id: str | None = None

    def __post_init__(self) -> None:
        if not self.schedule_id.strip():
            raise ValueError("fee schedule_id is required")
        for name in ("maker_bps", "taker_bps", "commission_per_unit_usd"):
            value = getattr(self, name)
            if value is not None and (not isfinite(value) or value < 0):
                raise ValueError(f"{name} must be nonnegative and finite when present")


@dataclass(frozen=True, slots=True)
class ProviderCard:
    provider_id: str
    role: ProviderRole
    venue: str
    fee_schedule: ProviderFeeSchedule
    entitlement: str

    def __post_init__(self) -> None:
        if not self.provider_id.strip():
            raise ValueError("provider_id is required")
        if not self.venue.strip():
            raise ValueError("venue is required")
        if not self.entitlement.strip():
            raise ValueError("entitlement is required")

    @property
    def can_observe(self) -> bool:
        return self.role in {ProviderRole.OBSERVE, ProviderRole.BOTH}

    @property
    def can_execute(self) -> bool:
        return self.role in {ProviderRole.EXECUTE, ProviderRole.BOTH}


class ProviderCardRegistry:
    def __init__(self, cards: tuple[ProviderCard, ...] = ()) -> None:
        by_id: dict[str, ProviderCard] = {}
        for card in cards:
            key = card.provider_id.strip().lower()
            if key in by_id:
                raise ValueError(f"duplicate provider card: {key}")
            by_id[key] = card
        self._cards = by_id

    def get(self, provider_id: str) -> ProviderCard | None:
        return self._cards.get(str(provider_id).strip().lower())

    def require(self, provider_id: str) -> ProviderCard:
        card = self.get(provider_id)
        if card is None:
            raise KeyError(f"unknown provider card: {provider_id}")
        return card

    def cards(self) -> tuple[ProviderCard, ...]:
        return tuple(self._cards[key] for key in sorted(self._cards))
