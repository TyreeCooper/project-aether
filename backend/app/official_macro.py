"""Primary-source macro schedule verification for Aether.

Forex Factory remains a calendar aggregator. BLS events are independently
checked against the Bureau of Labor Statistics' official iCalendar feed before
the event receives an official-verification flag. Failure to reach BLS never
turns an unverified event into a verified one.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any
from zoneinfo import ZoneInfo

import httpx

BLS_ICS = "https://www.bls.gov/schedule/news_release/bls.ics"
EASTERN = ZoneInfo("America/New_York")

BLS_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cpi", ("consumer price index", "cpi", "core cpi")),
    ("ppi", ("producer price index", "ppi", "core ppi")),
    (
        "employment_situation",
        (
            "employment situation",
            "non-farm",
            "nonfarm",
            "unemployment rate",
            "average hourly earnings",
        ),
    ),
    (
        "jolts",
        (
            "job openings and labor turnover",
            "jolts",
        ),
    ),
)


def _unfold_ics(text: str) -> list[str]:
    rows: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and rows:
            rows[-1] += raw[1:]
        else:
            rows.append(raw)
    return rows


def _parse_ics_dt(key: str, value: str) -> datetime | None:
    raw = value.strip()
    if "VALUE=DATE" in key:
        return None
    try:
        if raw.endswith("Z"):
            return datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(
                tzinfo=timezone.utc
            )
        parsed = datetime.strptime(raw, "%Y%m%dT%H%M%S")
    except ValueError:
        return None
    if "TZID=" in key:
        zone_name = key.split("TZID=", 1)[1].split(";", 1)[0].split(":", 1)[0]
        try:
            zone = ZoneInfo(zone_name)
        except Exception:
            zone = EASTERN
        return parsed.replace(tzinfo=zone).astimezone(timezone.utc)
    # BLS release-calendar times are Eastern Time.
    return parsed.replace(tzinfo=EASTERN).astimezone(timezone.utc)


def parse_bls_ics(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    current: dict[str, str] | None = None
    for line in _unfold_ics(text):
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current:
                summary = current.get("SUMMARY", "").replace("\\,", ",").strip()
                dt_key = next(
                    (key for key in current if key.startswith("DTSTART")),
                    None,
                )
                when = (
                    _parse_ics_dt(dt_key, current[dt_key])
                    if dt_key is not None
                    else None
                )
                if summary and when is not None:
                    events.append(
                        {
                            "title": summary,
                            "scheduled_at": when.isoformat(),
                            "source": "U.S. Bureau of Labor Statistics",
                            "source_url": BLS_ICS,
                        }
                    )
            current = None
            continue
        if current is None or ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key.startswith("SUMMARY"):
            current["SUMMARY"] = value
        elif key.startswith("DTSTART"):
            current[key] = value
    events.sort(key=lambda row: str(row.get("scheduled_at") or ""))
    return events


def _family(title: str) -> str | None:
    lower = re.sub(r"\s+", " ", str(title or "").lower()).strip()
    for family, terms in BLS_FAMILIES:
        if any(term in lower for term in terms):
            return family
    return None


def verify_bls_event(
    event: dict[str, Any],
    official_events: list[dict[str, Any]],
    *,
    tolerance_minutes: int = 5,
) -> dict[str, Any]:
    family = _family(str(event.get("title") or ""))
    if family is None:
        return {
            **event,
            "verified_official": False,
            "official_verification_status": "not_bls_family",
        }
    try:
        target = datetime.fromisoformat(
            str(event.get("scheduled_at") or "").replace("Z", "+00:00")
        )
    except ValueError:
        return {
            **event,
            "verified_official": False,
            "official_verification_status": "invalid_aggregator_time",
        }
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)

    matches = []
    for candidate in official_events:
        if _family(str(candidate.get("title") or "")) != family:
            continue
        try:
            official_time = datetime.fromisoformat(
                str(candidate.get("scheduled_at") or "").replace("Z", "+00:00")
            )
        except ValueError:
            continue
        delta_min = abs((official_time - target).total_seconds()) / 60
        if delta_min <= max(0, int(tolerance_minutes)):
            matches.append((delta_min, candidate))

    if not matches:
        return {
            **event,
            "verified_official": False,
            "official_verification_status": "official_schedule_mismatch",
            "official_source": "U.S. Bureau of Labor Statistics",
        }

    _, match = min(matches, key=lambda item: item[0])
    return {
        **event,
        "verified_official": True,
        "official_verification_status": "matched_primary_schedule",
        "official_source": match.get("source"),
        "official_source_url": match.get("source_url"),
        "official_scheduled_at": match.get("scheduled_at"),
    }


async def fetch_bls_schedule() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(
                BLS_ICS,
                headers={"User-Agent": "Project-Aether/1.0 macro-verification"},
            )
            response.raise_for_status()
            events = parse_bls_ics(response.text)
    except Exception as exc:
        return {
            "source": "U.S. Bureau of Labor Statistics",
            "connected": False,
            "status": "degraded",
            "events": [],
            "error": type(exc).__name__,
        }
    return {
        "source": "U.S. Bureau of Labor Statistics",
        "connected": True,
        "status": "connected",
        "events": events,
    }


async def verify_macro_events(
    events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    bls = await fetch_bls_schedule()
    official_events = list(bls.get("events") or [])
    verified = [
        verify_bls_event(event, official_events)
        if str(event.get("country") or "") == "USD"
        else dict(event)
        for event in events
    ]
    return verified, {
        "bls": {
            "connected": bool(bls.get("connected")),
            "status": str(bls.get("status") or "unavailable"),
            "events_loaded": len(official_events),
        },
        "federal_reserve": {
            "connected": False,
            "status": "planned",
            "note": "FOMC primary-source date verification not wired yet.",
        },
        "bea": {
            "connected": False,
            "status": "planned",
            "note": "BEA primary-source schedule verification not wired yet.",
        },
    }
