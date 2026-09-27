from __future__ import annotations

from datetime import date, datetime, time, timezone

import pytest

from aether_vnext.calendars import CalendarExceptionKind
from aether_vnext.tradinghours_calendar import (
    TRADINGHOURS_API_BASE,
    TRADINGHOURS_CALENDAR_PROVIDER_ID,
    TradingHoursCalendarProvider,
    fetch_tradinghours_calendar_snapshot,
    parse_tradinghours_daily_schedule,
)


UTC = timezone.utc
SESSION_DATE = date(2026, 11, 27)


def _payload(
    *,
    is_open: bool,
    end: str | None = None,
) -> dict:
    schedule = []
    if end is not None:
        schedule.append(
            {
                "phase_type": "Primary Trading Session",
                "phase_name": "Core Trading Session",
                "status": "Open",
                "start": "2026-11-27T09:30:00-05:00",
                "end": end,
            }
        )
    return {
        "data": {
            "date": SESSION_DATE.isoformat(),
            "day_of_week": "Friday",
            "is_open": is_open,
            "has_settlement": is_open,
            "holiday": "Thanksgiving Schedule",
            "schedule": schedule,
        }
    }


def test_closed_authoritative_schedule_maps_to_holiday() -> None:
    exception = parse_tradinghours_daily_schedule(
        _payload(is_open=False),
        calendar_id="us_rth",
        session_date=SESSION_DATE,
    )
    assert exception.kind is CalendarExceptionKind.HOLIDAY
    assert exception.early_close_et is None


def test_us_rth_partial_day_derives_exact_early_close_from_open_phase() -> None:
    exception = parse_tradinghours_daily_schedule(
        _payload(
            is_open=True,
            end="2026-11-27T13:00:00-05:00",
        ),
        calendar_id="us_rth",
        session_date=SESSION_DATE,
    )
    assert exception.kind is CalendarExceptionKind.EARLY_CLOSE
    assert exception.early_close_et == time(13, 0)


def test_us_rth_normal_day_remains_normal() -> None:
    exception = parse_tradinghours_daily_schedule(
        _payload(
            is_open=True,
            end="2026-11-27T16:00:00-05:00",
        ),
        calendar_id="us_rth",
        session_date=SESSION_DATE,
    )
    assert exception.kind is CalendarExceptionKind.NORMAL
    assert exception.early_close_et is None


def test_futures_early_close_ignores_later_evening_restart() -> None:
    payload = _payload(
        is_open=True,
        end="2026-11-27T13:00:00-05:00",
    )
    payload["data"]["schedule"].append(
        {
            "phase_type": "Primary Trading Session",
            "phase_name": "Next Session",
            "status": "Open",
            "start": "2026-11-27T18:00:00-05:00",
            "end": "2026-11-28T17:00:00-05:00",
        }
    )
    exception = parse_tradinghours_daily_schedule(
        payload,
        calendar_id="us_fut_idx",
        session_date=SESSION_DATE,
    )
    assert exception.kind is CalendarExceptionKind.EARLY_CLOSE
    assert exception.early_close_et == time(13, 0)


def test_open_day_without_authoritative_close_fails_closed() -> None:
    with pytest.raises(ValueError, match="authoritative open-phase close"):
        parse_tradinghours_daily_schedule(
            _payload(is_open=True),
            calendar_id="us_rth",
            session_date=SESSION_DATE,
        )


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class FakeClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    async def get(self, url: str, *, params: dict, headers: dict):
        self.calls.append(
            {"url": url, "params": params, "headers": headers}
        )
        return FakeResponse(self.payload)


@pytest.mark.asyncio
async def test_fetch_uses_bearer_auth_and_returns_sync_snapshot_provider() -> None:
    client = FakeClient(
        _payload(
            is_open=True,
            end="2026-11-27T13:00:00-05:00",
        )
    )
    snapshot = await fetch_tradinghours_calendar_snapshot(
        api_token="secret-token",
        calendar_market_ids={"us_rth": "US.NYSE"},
        session_dates=(SESSION_DATE,),
        client=client,
        fetched_at_utc=datetime(2026, 11, 26, 18, tzinfo=UTC),
    )

    assert snapshot.provider_id == TRADINGHOURS_CALENDAR_PROVIDER_ID
    assert snapshot.source_market_ids["us_rth"] == "US.NYSE"
    assert client.calls == [
        {
            "url": f"{TRADINGHOURS_API_BASE}/markets/hours",
            "params": {
                "fin_id": "US.NYSE",
                "date": SESSION_DATE.isoformat(),
            },
            "headers": {
                "Accept": "application/json",
                "Authorization": "Bearer secret-token",
            },
        }
    ]

    provider = TradingHoursCalendarProvider(snapshot)
    exception = provider.exception_for(
        calendar_id="us_rth",
        session_date=SESSION_DATE,
    )
    assert exception is not None
    assert exception.kind is CalendarExceptionKind.EARLY_CLOSE
    assert provider.exception_for(
        calendar_id="us_rth",
        session_date=date(2026, 11, 28),
    ) is None
