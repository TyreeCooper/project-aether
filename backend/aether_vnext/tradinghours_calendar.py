"""TradingHours-backed calendar snapshot provider for AETHER vNext.

The AETHER Master forbids hardcoded display clocks from acting as the authoritative
scheduler. This adapter fetches date-specific schedule truth from TradingHours and
converts it into the narrow CalendarException contract used by calendars.py.

Network I/O is deliberately separated from calendar_decision(): callers prefetch a
snapshot asynchronously, then pass the immutable in-memory provider into synchronous
Firm decision logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from types import MappingProxyType
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import httpx

from aether_vnext.calendars import (
    CalendarException,
    CalendarExceptionKind,
)


ET = ZoneInfo("America/New_York")
TRADINGHOURS_CALENDAR_PROVIDER_ID = "tradinghours_v3"
TRADINGHOURS_API_BASE = "https://api.tradinghours.com/v3"

# Canonical AETHER eligibility/session close, not provider-derived display text.
# A provider schedule ending earlier than this boundary is an early close.
_CANONICAL_ELIGIBILITY_CLOSE_ET = MappingProxyType(
    {
        "us_rth": time(16, 0),
        "us_fut_idx": time(17, 0),
        "us_fut_metal_nrg": time(17, 0),
        "us_fut_rates": time(17, 0),
    }
)


@dataclass(frozen=True, slots=True)
class TradingHoursScheduleIdentity:
    calendar_id: str
    market_id: str
    session_date: date


@dataclass(frozen=True, slots=True)
class TradingHoursCalendarSnapshot:
    provider_id: str
    exceptions: Mapping[tuple[str, date], CalendarException]
    source_market_ids: Mapping[str, str]
    fetched_at_utc: datetime

    def __post_init__(self) -> None:
        if self.provider_id != TRADINGHOURS_CALENDAR_PROVIDER_ID:
            raise ValueError("unexpected TradingHours provider_id")
        if self.fetched_at_utc.tzinfo is None:
            raise ValueError("fetched_at_utc must be timezone-aware")


class TradingHoursCalendarProvider:
    """Synchronous CalendarExceptionProvider backed by a prefetched snapshot."""

    provider_id = TRADINGHOURS_CALENDAR_PROVIDER_ID

    def __init__(self, snapshot: TradingHoursCalendarSnapshot) -> None:
        self.snapshot = snapshot

    def exception_for(
        self,
        *,
        calendar_id: str,
        session_date: date,
    ) -> CalendarException | None:
        return self.snapshot.exceptions.get(
            (str(calendar_id).strip(), session_date)
        )


def _parse_iso(value: object) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("TradingHours schedule timestamp missing")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"invalid TradingHours schedule timestamp: {text}"
        ) from exc
    if parsed.tzinfo is None:
        raise ValueError("TradingHours schedule timestamp must be timezone-aware")
    return parsed


def parse_tradinghours_daily_schedule(
    payload: object,
    *,
    calendar_id: str,
    session_date: date,
) -> CalendarException:
    """Convert one TradingHours daily schedule into AETHER date-specific truth."""
    calendar = str(calendar_id).strip()
    if calendar not in _CANONICAL_ELIGIBILITY_CLOSE_ET:
        raise ValueError(
            f"TradingHours calendar unsupported by AETHER provider: {calendar}"
        )
    if not isinstance(payload, dict):
        raise ValueError("TradingHours payload must be an object")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("TradingHours payload missing data object")

    response_date = str(data.get("date") or "").strip()
    if response_date != session_date.isoformat():
        raise ValueError(
            "TradingHours response date does not match requested session date"
        )

    is_open = data.get("is_open")
    if not isinstance(is_open, bool):
        raise ValueError("TradingHours is_open must be boolean")
    if not is_open:
        return CalendarException(
            calendar_id=calendar,
            session_date=session_date,
            kind=CalendarExceptionKind.HOLIDAY,
        )

    schedule = data.get("schedule")
    if not isinstance(schedule, list):
        raise ValueError("TradingHours schedule must be a list")

    canonical_close = _CANONICAL_ELIGIBILITY_CLOSE_ET[calendar]
    canonical_close_minutes = (
        canonical_close.hour * 60 + canonical_close.minute
    )
    candidate_end_minutes: list[int] = []

    for phase in schedule:
        if not isinstance(phase, dict):
            continue
        if str(phase.get("status") or "").strip().lower() != "open":
            continue
        end_et = _parse_iso(phase.get("end")).astimezone(ET)
        if end_et.date() != session_date:
            continue
        end_minutes = end_et.hour * 60 + end_et.minute
        # Ignore a later evening restart. We need the close immediately preceding
        # AETHER's daily maintenance/end-of-eligibility boundary.
        if end_minutes <= canonical_close_minutes:
            candidate_end_minutes.append(end_minutes)

    if not candidate_end_minutes:
        raise ValueError(
            "TradingHours open day lacks an authoritative open-phase close "
            "at or before the canonical AETHER eligibility boundary"
        )

    actual_close_minutes = max(candidate_end_minutes)
    if actual_close_minutes < canonical_close_minutes:
        return CalendarException(
            calendar_id=calendar,
            session_date=session_date,
            kind=CalendarExceptionKind.EARLY_CLOSE,
            early_close_et=time(
                actual_close_minutes // 60,
                actual_close_minutes % 60,
            ),
        )

    return CalendarException(
        calendar_id=calendar,
        session_date=session_date,
        kind=CalendarExceptionKind.NORMAL,
    )


async def fetch_tradinghours_calendar_snapshot(
    *,
    api_token: str,
    calendar_market_ids: Mapping[str, str],
    session_dates: tuple[date, ...],
    client: httpx.AsyncClient | None = None,
    fetched_at_utc: datetime,
) -> TradingHoursCalendarSnapshot:
    """Fetch exact daily schedules for configured AETHER calendar IDs."""
    token = str(api_token).strip()
    if not token:
        raise ValueError("TradingHours API token is required")
    if fetched_at_utc.tzinfo is None:
        raise ValueError("fetched_at_utc must be timezone-aware")
    if not session_dates:
        raise ValueError("at least one session_date is required")

    normalized_market_ids: dict[str, str] = {}
    for raw_calendar, raw_market in calendar_market_ids.items():
        calendar = str(raw_calendar).strip()
        market_id = str(raw_market).strip()
        if calendar not in _CANONICAL_ELIGIBILITY_CLOSE_ET:
            raise ValueError(
                f"unsupported TradingHours AETHER calendar_id: {calendar}"
            )
        if not market_id:
            raise ValueError(
                f"TradingHours market_id missing for calendar: {calendar}"
            )
        normalized_market_ids[calendar] = market_id
    if not normalized_market_ids:
        raise ValueError("calendar_market_ids must be non-empty")

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=12.0)
    exceptions: dict[tuple[str, date], CalendarException] = {}
    try:
        for calendar_id, market_id in sorted(normalized_market_ids.items()):
            for session_date in sorted(set(session_dates)):
                response = await http.get(
                    f"{TRADINGHOURS_API_BASE}/markets/hours",
                    params={
                        "fin_id": market_id,
                        "date": session_date.isoformat(),
                    },
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Bearer {token}",
                    },
                )
                response.raise_for_status()
                exception = parse_tradinghours_daily_schedule(
                    response.json(),
                    calendar_id=calendar_id,
                    session_date=session_date,
                )
                exceptions[(calendar_id, session_date)] = exception
    finally:
        if owns_client:
            await http.aclose()

    return TradingHoursCalendarSnapshot(
        provider_id=TRADINGHOURS_CALENDAR_PROVIDER_ID,
        exceptions=MappingProxyType(dict(exceptions)),
        source_market_ids=MappingProxyType(dict(normalized_market_ids)),
        fetched_at_utc=fetched_at_utc,
    )
