"""Implemented calendar-provider capability registry for AETHER vNext.

The weekly session rules in calendars.py are Firm logic. Non-24x7 date-specific
holiday/early-close truth must come from an implemented authoritative provider.
Naming a provider in runtime configuration is not enough.

TradingHours is registered for the exchange-calendar IDs used by futures and
equities. FX OTC and crypto keep their frozen internal weekly/24x7 calendar contracts.
Canonical burn-in still fails closed until reviewed provider market IDs are bound where
the registered provider requires them.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from aether_vnext.tradinghours_calendar import (
    TRADINGHOURS_CALENDAR_PROVIDER_ID,
)


@dataclass(frozen=True, slots=True)
class CalendarProviderCapability:
    provider_id: str
    supported_calendar_ids: frozenset[str]
    requires_market_id: bool = False
    implemented: bool = True

    def supports_calendar(self, calendar_id: str) -> bool:
        return str(calendar_id).strip() in self.supported_calendar_ids


EXTERNAL_CALENDAR_PROVIDER_IDS: Final = frozenset(
    {
        "us_rth",
        "us_fut_idx",
        "us_fut_metal_nrg",
        "us_fut_rates",
    }
)


def calendar_requires_external_provider(calendar_id: str) -> bool:
    """Whether frozen AETHER truth requires date-specific exchange-calendar data."""
    return str(calendar_id).strip() in EXTERNAL_CALENDAR_PROVIDER_IDS


IMPLEMENTED_CALENDAR_PROVIDERS: Final = MappingProxyType(
    {
        TRADINGHOURS_CALENDAR_PROVIDER_ID: CalendarProviderCapability(
            provider_id=TRADINGHOURS_CALENDAR_PROVIDER_ID,
            supported_calendar_ids=frozenset(
                {
                    "us_rth",
                    "us_fut_idx",
                    "us_fut_metal_nrg",
                    "us_fut_rates",
                }
            ),
            requires_market_id=True,
        )
    }
)


def calendar_provider_capability(
    provider_id: str | None,
) -> CalendarProviderCapability | None:
    if provider_id is None:
        return None
    return IMPLEMENTED_CALENDAR_PROVIDERS.get(str(provider_id).strip())


def calendar_provider_implementation_blockers(
    *,
    calendar_id: str,
    provider_id: str | None,
    market_id: str | None = None,
) -> tuple[str, ...]:
    calendar = str(calendar_id).strip()
    if calendar in {"crypto_24x7", "fx_otc"}:
        return ()

    provider = None if provider_id is None else str(provider_id).strip()
    if not provider:
        return ("calendar_provider_missing",)

    capability = calendar_provider_capability(provider)
    if capability is None or not capability.implemented:
        return ("calendar_provider_implementation_missing",)
    if not capability.supports_calendar(calendar):
        return ("calendar_provider_calendar_unsupported",)
    if capability.requires_market_id and not str(market_id or "").strip():
        return ("calendar_provider_market_id_missing",)
    return ()
