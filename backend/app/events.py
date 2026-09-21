"""Macro/event-risk feed for the Aether paper desk.

Forex Factory's public weekly JSON export is used as a calendar aggregator.
Events are normalized into crypto risk windows. This module never submits orders.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

FF_WEEKLY_JSON = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

MAJOR_US_TITLES = (
    "cpi",
    "consumer price",
    "non-farm",
    "nonfarm",
    "employment change",
    "unemployment rate",
    "fomc",
    "federal funds",
    "fed chair",
    "pce",
    "ppi",
    "producer price",
    "gdp",
)


def _parse_dt(raw: Any) -> datetime | None:
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def normalize_event(row: dict[str, Any]) -> dict[str, Any] | None:
    when = _parse_dt(row.get("date"))
    if when is None:
        return None
    title = str(row.get("title") or "").strip()
    country = str(row.get("country") or "").upper()
    impact = str(row.get("impact") or "Low").title()
    lower = title.lower()
    major_us = country == "USD" and any(x in lower for x in MAJOR_US_TITLES)

    # Crypto never closes. These are entry-risk windows, not market closures.
    if major_us or (country == "USD" and impact == "High"):
        before_min, after_min, state = 15, 30, "restricted"
    elif country == "USD" and impact == "Medium":
        before_min, after_min, state = 10, 15, "caution"
    elif country == "USD" and impact == "Holiday":
        before_min, after_min, state = 0, 24 * 60, "caution"
    elif impact == "High":
        before_min, after_min, state = 10, 15, "caution"
    else:
        before_min, after_min, state = 0, 0, "normal"

    return {
        "title": title,
        "country": country,
        "impact": impact,
        "scheduled_at": when.astimezone(timezone.utc).isoformat(),
        "forecast": row.get("forecast") or None,
        "previous": row.get("previous") or None,
        "state": state,
        "window_before_min": before_min,
        "window_after_min": after_min,
        "window_start": (when - timedelta(minutes=before_min)).astimezone(timezone.utc).isoformat(),
        "window_end": (when + timedelta(minutes=after_min)).astimezone(timezone.utc).isoformat(),
        "source": "Forex Factory",
        "verified_official": False,
    }


def active_risk(events: list[dict[str, Any]], now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    active: list[dict[str, Any]] = []
    upcoming: list[dict[str, Any]] = []
    for event in events:
        start = _parse_dt(event.get("window_start"))
        end = _parse_dt(event.get("window_end"))
        scheduled = _parse_dt(event.get("scheduled_at"))
        if not start or not end or not scheduled:
            continue
        if start <= current <= end and event.get("state") != "normal":
            active.append(event)
        elif current < scheduled <= current + timedelta(hours=24):
            upcoming.append(event)
    state = (
        "restricted"
        if any(x.get("state") == "restricted" for x in active)
        else "caution"
        if active
        else "normal"
    )
    upcoming.sort(key=lambda x: str(x.get("scheduled_at") or ""))
    return {
        "state": state,
        "new_entries_allowed": state != "restricted",
        "active_events": active,
        "upcoming_24h": upcoming[:20],
    }


async def fetch_calendar() -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            FF_WEEKLY_JSON,
            headers={"User-Agent": "Project-Aether/1.0 calendar-risk"},
        )
        response.raise_for_status()
        raw = response.json()
    if not isinstance(raw, list):
        return []
    events = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        normalized = normalize_event(row)
        if normalized is not None:
            events.append(normalized)
    events.sort(key=lambda x: str(x.get("scheduled_at") or ""))
    return events
