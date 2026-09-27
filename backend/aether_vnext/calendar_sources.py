"""Implemented calendar-provider capability registry for AETHER vNext.

The weekly session rules in calendars.py are Firm logic. Non-24x7 date-specific
holiday/early-close truth must come from an implemented authoritative provider.
Naming a provider in runtime configuration is not enough.

There is intentionally no non-crypto provider registered yet. Until one is
implemented, canonical burn-in remains fail-closed for FX, futures, and equities.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final


@dataclass(frozen=True, slots=True)
class CalendarProviderCapability:
    provider_id: str
    supported_calendar_ids: frozenset[str]
    implemented: bool = True

    def supports_calendar(self, calendar_id: str) -> bool:
        return str(calendar_id).strip() in self.supported_calendar_ids


IMPLEMENTED_CALENDAR_PROVIDERS: Final = MappingProxyType({})


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
) -> tuple[str, ...]:
    calendar = str(calendar_id).strip()
    if calendar == "crypto_24x7":
        return ()

    provider = None if provider_id is None else str(provider_id).strip()
    if not provider:
        return ("calendar_provider_missing",)

    capability = calendar_provider_capability(provider)
    if capability is None or not capability.implemented:
        return ("calendar_provider_implementation_missing",)
    if not capability.supports_calendar(calendar):
        return ("calendar_provider_calendar_unsupported",)
    return ()
