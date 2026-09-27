"""Probe configured TradingHours calendar mappings for AETHER vNext.

This command reads durable runtime Product Registry bindings from the isolated vNext
book, derives the exact configured AETHER calendar_id -> TradingHours market identity
map, fetches authoritative daily schedules, and emits the normalized CalendarException
snapshot. It does not create trading authority or change campaign state.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from aether_vnext.db_runtime import open_vnext_engine
from aether_vnext.registry import registry_row
from aether_vnext.store import VNextStore
from aether_vnext.tradinghours_calendar import (
    TRADINGHOURS_CALENDAR_PROVIDER_ID,
    fetch_tradinghours_calendar_snapshot,
)


ET = ZoneInfo("America/New_York")


def _calendar_map(rows: tuple[dict, ...]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in rows:
        binding = row["binding"]
        if binding.calendar_provider_id != TRADINGHOURS_CALENDAR_PROVIDER_ID:
            continue
        calendar_id = registry_row(binding.asset_id).calendar_id
        market_id = str(binding.calendar_market_id or "").strip()
        if not market_id:
            raise ValueError(
                f"TradingHours calendar_market_id missing for {binding.asset_id}"
            )
        existing = out.get(calendar_id)
        if existing is not None and existing != market_id:
            raise ValueError(
                f"conflicting TradingHours market IDs for {calendar_id}: "
                f"{existing} vs {market_id}"
            )
        out[calendar_id] = market_id
    if not out:
        raise RuntimeError(
            "no durable TradingHours calendar bindings found in vNext registry"
        )
    return out


def _serialize(snapshot) -> dict[str, object]:
    rows = []
    for (calendar_id, session_date), exception in sorted(
        snapshot.exceptions.items(),
        key=lambda item: (item[0][0], item[0][1]),
    ):
        rows.append(
            {
                "calendar_id": calendar_id,
                "market_id": snapshot.source_market_ids[calendar_id],
                "session_date": session_date.isoformat(),
                "kind": exception.kind.value,
                "early_close_et": (
                    None
                    if exception.early_close_et is None
                    else exception.early_close_et.isoformat()
                ),
            }
        )
    return {
        "provider_id": snapshot.provider_id,
        "fetched_at_utc": snapshot.fetched_at_utc.isoformat(),
        "calendar_count": len(snapshot.source_market_ids),
        "exception_count": len(rows),
        "calendar_market_ids": dict(snapshot.source_market_ids),
        "exceptions": rows,
    }


def _emit(payload: dict[str, object], output: str | None) -> None:
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    print(rendered)
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")


async def _main(
    *,
    session_date: date,
    output: str | None,
) -> int:
    token = os.getenv("AETHER_VNEXT_TRADINGHOURS_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "AETHER_VNEXT_TRADINGHOURS_API_TOKEN is required"
        )

    store = VNextStore(schema="aether_vnext")
    async with open_vnext_engine() as engine:
        async with engine.connect() as connection:
            bindings = await connection.run_sync(
                lambda sync_conn: store.list_runtime_registry_bindings(sync_conn)
            )

    calendar_market_ids = _calendar_map(bindings)
    fetched_at_utc = datetime.now(timezone.utc)
    snapshot = await fetch_tradinghours_calendar_snapshot(
        api_token=token,
        calendar_market_ids=calendar_market_ids,
        session_dates=(session_date,),
        fetched_at_utc=fetched_at_utc,
    )
    _emit(_serialize(snapshot), output)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--date",
        help="session date YYYY-MM-DD; defaults to current America/New_York date",
    )
    parser.add_argument("--output")
    args = parser.parse_args()
    target = (
        date.fromisoformat(args.date)
        if args.date
        else datetime.now(ET).date()
    )
    raise SystemExit(
        asyncio.run(
            _main(
                session_date=target,
                output=args.output,
            )
        )
    )
