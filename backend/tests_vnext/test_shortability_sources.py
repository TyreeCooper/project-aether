from __future__ import annotations

from aether_vnext.ibkr_webapi_market import (
    IBKR_WEBAPI_SHORTABILITY_PROVIDER_ID,
)
from aether_vnext.shortability_sources import (
    IMPLEMENTED_SHORTABILITY_PROVIDERS,
    shortability_provider_implementation_blockers,
)


def test_ibkr_shortability_provider_is_implemented_for_equities_only() -> None:
    assert set(IMPLEMENTED_SHORTABILITY_PROVIDERS) == {
        IBKR_WEBAPI_SHORTABILITY_PROVIDER_ID
    }
    capability = IMPLEMENTED_SHORTABILITY_PROVIDERS[
        IBKR_WEBAPI_SHORTABILITY_PROVIDER_ID
    ]
    assert capability.implemented is True
    assert capability.supported_assets == frozenset({"nvda", "tsla", "pltr"})

    assert shortability_provider_implementation_blockers(
        provider_id=IBKR_WEBAPI_SHORTABILITY_PROVIDER_ID,
        asset_id="nvda",
    ) == ()
    assert shortability_provider_implementation_blockers(
        provider_id=IBKR_WEBAPI_SHORTABILITY_PROVIDER_ID,
        asset_id="btc",
    ) == ("shortability_provider_asset_unsupported",)


def test_unknown_shortability_provider_remains_fail_closed() -> None:
    assert shortability_provider_implementation_blockers(
        provider_id="reviewed.locate",
        asset_id="nvda",
    ) == ("shortability_provider_implementation_missing",)
