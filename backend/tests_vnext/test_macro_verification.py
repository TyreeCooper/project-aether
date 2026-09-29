from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aether_vnext.macro_verification import (
    MacroVerificationRequest,
    PrimaryMacroScheduleEvent,
    verify_primary_macro_schedule,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 16, 18, 0, tzinfo=UTC)


def _official(
    *,
    source_id: str = "federal_reserve",
    source_event_id: str = "fomc-2026-09",
    event_family: str = "fomc_rate_decision",
    scheduled_at_utc: datetime = T0,
) -> PrimaryMacroScheduleEvent:
    return PrimaryMacroScheduleEvent(
        source_id=source_id,
        source_event_id=source_event_id,
        event_family=event_family,
        scheduled_at_utc=scheduled_at_utc,
        title="Federal Open Market Committee decision",
        source_url="https://www.federalreserve.gov/",
        observed_at_utc=T0 - timedelta(days=10),
    )


def _request(
    *,
    event_family: str = "fomc_rate_decision",
    scheduled_at_utc: datetime = T0,
) -> MacroVerificationRequest:
    return MacroVerificationRequest(
        event_id="calendar-event-1",
        event_family=event_family,
        scheduled_at_utc=scheduled_at_utc,
        aggregator_source_id="forex_factory",
    )


@pytest.mark.parametrize("source_id", ("bls", "federal_reserve", "bea"))
def test_primary_macro_event_accepts_approved_authorities(source_id: str) -> None:
    event = _official(source_id=source_id)
    assert event.source_id == source_id


def test_primary_macro_event_rejects_unapproved_authority() -> None:
    with pytest.raises(
        ValueError,
        match="approved primary macro source",
    ):
        _official(source_id="forex_factory")


def test_macro_contracts_require_canonical_identity_and_aware_time() -> None:
    with pytest.raises(ValueError, match="event_family must be canonical text"):
        _request(event_family=" fomc_rate_decision ")

    with pytest.raises(ValueError, match="scheduled_at_utc must be timezone-aware"):
        _request(scheduled_at_utc=T0.replace(tzinfo=None))

    with pytest.raises(ValueError, match="source_event_id must be canonical text"):
        _official(source_event_id=" fomc-2026-09 ")


def test_primary_schedule_match_is_family_bound_and_fail_closed() -> None:
    official = (
        _official(
            source_id="federal_reserve",
            source_event_id="fomc",
            event_family="fomc_rate_decision",
        ),
        _official(
            source_id="bea",
            source_event_id="gdp",
            event_family="gdp_release",
        ),
    )

    matched = verify_primary_macro_schedule(_request(), official)
    assert matched.verified_official is True
    assert matched.verification_status == "matched_primary_schedule"
    assert matched.primary_source_id == "federal_reserve"
    assert matched.primary_source_event_id == "fomc"
    assert matched.delta_seconds == 0.0

    mismatch = verify_primary_macro_schedule(
        _request(event_family="personal_income_outlays"),
        official,
    )
    assert mismatch.verified_official is False
    assert mismatch.verification_status == "primary_schedule_mismatch"
    assert mismatch.primary_source_id is None


def test_primary_schedule_uses_closest_in_tolerance_deterministically() -> None:
    official = (
        _official(
            source_event_id="later",
            scheduled_at_utc=T0 + timedelta(minutes=4),
        ),
        _official(
            source_event_id="closer",
            scheduled_at_utc=T0 + timedelta(minutes=1),
        ),
    )

    result = verify_primary_macro_schedule(
        _request(),
        official,
        tolerance_seconds=300,
    )

    assert result.verified_official is True
    assert result.primary_source_event_id == "closer"
    assert result.delta_seconds == 60.0


def test_primary_schedule_rejects_invalid_tolerance_and_out_of_window_match() -> None:
    with pytest.raises(
        ValueError,
        match="tolerance_seconds must be a nonnegative integer",
    ):
        verify_primary_macro_schedule(
            _request(),
            (),
            tolerance_seconds=True,
        )

    result = verify_primary_macro_schedule(
        _request(),
        (
            _official(
                scheduled_at_utc=T0 + timedelta(minutes=6),
            ),
        ),
        tolerance_seconds=300,
    )
    assert result.verified_official is False


def test_verified_result_requires_primary_source_provenance() -> None:
    result = verify_primary_macro_schedule(_request(), (_official(),))
    assert result.primary_source_url is not None
    assert result.official_scheduled_at_utc == T0
