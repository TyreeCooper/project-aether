"""Implemented shortability-provider capability registry for AETHER vNext.

A provider ID in runtime configuration is only a name until repository code exists
that can produce provider-derived borrow evidence for the asset family.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from aether_vnext.ibkr_webapi_market import (
    IBKR_WEBAPI_SHORTABILITY_PROVIDER_ID,
)


@dataclass(frozen=True, slots=True)
class ShortabilityProviderCapability:
    provider_id: str
    supported_assets: frozenset[str]
    implemented: bool = True

    def supports_asset(self, asset_id: str) -> bool:
        return str(asset_id).strip().lower() in self.supported_assets


IMPLEMENTED_SHORTABILITY_PROVIDERS: Final = MappingProxyType(
    {
        IBKR_WEBAPI_SHORTABILITY_PROVIDER_ID: ShortabilityProviderCapability(
            provider_id=IBKR_WEBAPI_SHORTABILITY_PROVIDER_ID,
            supported_assets=frozenset({"nvda", "tsla", "pltr"}),
        )
    }
)


def shortability_provider_capability(
    provider_id: str | None,
) -> ShortabilityProviderCapability | None:
    if provider_id is None:
        return None
    return IMPLEMENTED_SHORTABILITY_PROVIDERS.get(str(provider_id).strip())


def shortability_provider_implementation_blockers(
    *,
    provider_id: str | None,
    asset_id: str,
) -> tuple[str, ...]:
    provider = None if provider_id is None else str(provider_id).strip()
    if not provider:
        return ("shortability_provider_missing",)

    capability = shortability_provider_capability(provider)
    if capability is None or not capability.implemented:
        return ("shortability_provider_implementation_missing",)
    if not capability.supports_asset(asset_id):
        return ("shortability_provider_asset_unsupported",)
    return ()
