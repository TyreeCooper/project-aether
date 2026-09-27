from __future__ import annotations

from aether_vnext.calendar_sources import (
    IMPLEMENTED_CALENDAR_PROVIDERS,
    calendar_provider_implementation_blockers,
)
from aether_vnext.tradinghours_calendar import (
    TRADINGHOURS_CALENDAR_PROVIDER_ID,
)


def test_tradinghours_provider_is_registered_for_exchange_calendars() -> None:
    capability = IMPLEMENTED_CALENDAR_PROVIDERS[
        TRADINGHOURS_CALENDAR_PROVIDER_ID
    ]
    assert capability.implemented is True
    assert capability.requires_market_id is True
    assert capability.supported_calendar_ids == frozenset(
        {
            "us_rth",
            "us_fut_idx",
            "us_fut_metal_nrg",
            "us_fut_rates",
        }
    )


def test_crypto_24x7_needs_no_external_calendar_provider() -> None:
    assert calendar_provider_implementation_blockers(
        calendar_id="crypto_24x7",
        provider_id=None,
    ) == ()


def test_unknown_noncrypto_provider_is_not_mistaken_for_implemented_code() -> None:
    assert calendar_provider_implementation_blockers(
        calendar_id="us_fut_idx",
        provider_id="reviewed.calendar",
        market_id="reviewed.market",
    ) == ("calendar_provider_implementation_missing",)


def test_tradinghours_requires_reviewed_market_identity() -> None:
    assert calendar_provider_implementation_blockers(
        calendar_id="us_rth",
        provider_id=TRADINGHOURS_CALENDAR_PROVIDER_ID,
        market_id=None,
    ) == ("calendar_provider_market_id_missing",)

    assert calendar_provider_implementation_blockers(
        calendar_id="us_rth",
        provider_id=TRADINGHOURS_CALENDAR_PROVIDER_ID,
        market_id="US.NYSE",
    ) == ()


def test_fx_otc_does_not_require_exchange_calendar_provider() -> None:
    assert calendar_provider_implementation_blockers(
        calendar_id="fx_otc",
        provider_id=None,
        market_id=None,
    ) == ()
