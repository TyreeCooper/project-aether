"""Authoritative calendar scheduling contract for AETHER vNext.

The Master requires DST/holiday/early-close aware exchange calendars. Static clock
strings are display summaries only. This module therefore separates weekly session
rules from date-specific calendar exceptions and refuses to invent holiday state.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum
from typing import Protocol
from zoneinfo import ZoneInfo

from aether_vnext.domain import CalendarState, SessionState


ET = ZoneInfo("America/New_York")


class CalendarExceptionKind(StrEnum):
    NORMAL = "normal"
    HOLIDAY = "holiday"
    EARLY_CLOSE = "early_close"


@dataclass(frozen=True, slots=True)
class CalendarException:
    calendar_id: str
    session_date: date
    kind: CalendarExceptionKind
    early_close_et: time | None = None


class CalendarExceptionProvider(Protocol):
    def exception_for(
        self,
        *,
        calendar_id: str,
        session_date: date,
    ) -> CalendarException | None: ...


@dataclass(frozen=True, slots=True)
class CalendarDecision:
    calendar_id: str
    session_state: SessionState
    calendar_state: CalendarState
    eligible: bool
    focus: bool
    reason: str
    session_end_et: time | None = None


def _minute_of_day(ts_et: datetime) -> int:
    return ts_et.hour * 60 + ts_et.minute


def _in_window(cur: int, start: int, end: int) -> bool:
    if start == end:
        return True
    if start < end:
        return start <= cur < end
    return cur >= start or cur < end


def _weekend_fx_closed(ts_et: datetime) -> bool:
    # Friday 17:00 ET through Sunday 17:00 ET.
    weekday = ts_et.weekday()  # Mon=0
    cur = _minute_of_day(ts_et)
    if weekday == 4 and cur >= 17 * 60:
        return True
    if weekday == 5:
        return True
    if weekday == 6 and cur < 17 * 60:
        return True
    return False


def _weekend_futures_closed(ts_et: datetime) -> bool:
    # Friday 17:00 ET through Sunday 18:00 ET.
    weekday = ts_et.weekday()
    cur = _minute_of_day(ts_et)
    if weekday == 4 and cur >= 17 * 60:
        return True
    if weekday == 5:
        return True
    if weekday == 6 and cur < 18 * 60:
        return True
    return False


def _date_exception(
    *,
    calendar_id: str,
    ts_et: datetime,
    provider: CalendarExceptionProvider | None,
) -> CalendarException | None:
    if calendar_id == "crypto_24x7":
        return CalendarException(
            calendar_id=calendar_id,
            session_date=ts_et.date(),
            kind=CalendarExceptionKind.NORMAL,
        )
    if provider is None:
        return None
    return provider.exception_for(
        calendar_id=calendar_id,
        session_date=ts_et.date(),
    )


def calendar_decision(
    *,
    calendar_id: str,
    at_utc: datetime,
    exception_provider: CalendarExceptionProvider | None,
) -> CalendarDecision:
    if at_utc.tzinfo is None:
        raise ValueError("at_utc must be timezone-aware")
    ts = at_utc.astimezone(ET)
    cur = _minute_of_day(ts)

    if calendar_id == "crypto_24x7":
        return CalendarDecision(
            calendar_id=calendar_id,
            session_state=SessionState.ACTIVE,
            calendar_state=CalendarState.ALWAYS_OPEN,
            eligible=True,
            focus=True,
            reason="24x7",
        )

    exception = _date_exception(
        calendar_id=calendar_id,
        ts_et=ts,
        provider=exception_provider,
    )
    if exception is None:
        return CalendarDecision(
            calendar_id=calendar_id,
            session_state=SessionState.CLOSED,
            calendar_state=CalendarState.NORMAL,
            eligible=False,
            focus=False,
            reason="calendar_exception_provider_required",
        )
    if exception.kind is CalendarExceptionKind.HOLIDAY:
        return CalendarDecision(
            calendar_id=calendar_id,
            session_state=SessionState.CLOSED,
            calendar_state=CalendarState.HOLIDAY,
            eligible=False,
            focus=False,
            reason="holiday",
        )

    early_close_min = None
    if exception.kind is CalendarExceptionKind.EARLY_CLOSE:
        if exception.early_close_et is None:
            raise ValueError("early close exception requires early_close_et")
        early_close_min = exception.early_close_et.hour * 60 + exception.early_close_et.minute

    if calendar_id == "fx_otc":
        if _weekend_fx_closed(ts):
            return CalendarDecision(
                calendar_id=calendar_id,
                session_state=SessionState.CLOSED,
                calendar_state=CalendarState.NORMAL,
                eligible=False,
                focus=False,
                reason="weekend",
            )
        if early_close_min is not None and cur >= early_close_min:
            return CalendarDecision(
                calendar_id=calendar_id,
                session_state=SessionState.CLOSED,
                calendar_state=CalendarState.EARLY_CLOSE,
                eligible=False,
                focus=False,
                reason="early_close",
                session_end_et=time(
                    early_close_min // 60,
                    early_close_min % 60,
                ),
            )
        # Defined 16:59–17:05 ET rollover maintenance.
        if 16 * 60 + 59 <= cur < 17 * 60 + 5:
            return CalendarDecision(
                calendar_id=calendar_id,
                session_state=SessionState.MAINTENANCE,
                calendar_state=CalendarState.NORMAL,
                eligible=False,
                focus=False,
                reason="fx_rollover",
            )
        london = _in_window(cur, 3 * 60, 12 * 60)
        new_york = _in_window(cur, 8 * 60, 17 * 60)
        return CalendarDecision(
            calendar_id=calendar_id,
            session_state=SessionState.FOCUS if (london or new_york) else SessionState.ACTIVE,
            calendar_state=CalendarState.NORMAL,
            eligible=True,
            focus=london or new_york,
            reason="eligible",
            session_end_et=time(17, 0),
        )

    if calendar_id == "us_rth":
        close_min = early_close_min if early_close_min is not None else 16 * 60
        eligible = 9 * 60 + 30 <= cur < close_min
        return CalendarDecision(
            calendar_id=calendar_id,
            session_state=SessionState.FOCUS if eligible else SessionState.CLOSED,
            calendar_state=(
                CalendarState.EARLY_CLOSE
                if early_close_min is not None
                else CalendarState.NORMAL
            ),
            eligible=eligible,
            focus=eligible,
            reason="eligible" if eligible else "session_closed",
            session_end_et=time(close_min // 60, close_min % 60),
        )

    if calendar_id in {"us_fut_idx", "us_fut_metal_nrg", "us_fut_rates"}:
        if _weekend_futures_closed(ts):
            return CalendarDecision(
                calendar_id=calendar_id,
                session_state=SessionState.CLOSED,
                calendar_state=CalendarState.NORMAL,
                eligible=False,
                focus=False,
                reason="weekend",
            )
        if early_close_min is not None and cur >= early_close_min:
            return CalendarDecision(
                calendar_id=calendar_id,
                session_state=SessionState.CLOSED,
                calendar_state=CalendarState.EARLY_CLOSE,
                eligible=False,
                focus=False,
                reason="early_close",
                session_end_et=time(
                    early_close_min // 60,
                    early_close_min % 60,
                ),
            )
        if 17 * 60 <= cur < 18 * 60:
            return CalendarDecision(
                calendar_id=calendar_id,
                session_state=SessionState.MAINTENANCE,
                calendar_state=CalendarState.NORMAL,
                eligible=False,
                focus=False,
                reason="daily_maintenance",
            )
        focus_window = {
            "us_fut_idx": (9 * 60 + 30, 16 * 60),
            "us_fut_metal_nrg": (8 * 60, 13 * 60 + 30),
            "us_fut_rates": (8 * 60 + 20, 15 * 60),
        }[calendar_id]
        focus_end = (
            min(focus_window[1], early_close_min)
            if early_close_min is not None
            else focus_window[1]
        )
        focus = focus_window[0] <= cur < focus_end
        return CalendarDecision(
            calendar_id=calendar_id,
            session_state=SessionState.FOCUS if focus else SessionState.ACTIVE,
            calendar_state=(
                CalendarState.EARLY_CLOSE
                if early_close_min is not None
                else CalendarState.NORMAL
            ),
            eligible=True,
            focus=focus,
            reason="eligible",
            session_end_et=(
                time(focus_end // 60, focus_end % 60)
                if early_close_min is not None
                else None
            ),
        )

    raise KeyError(f"unknown calendar_id: {calendar_id}")
