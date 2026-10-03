"""GET-only operator surface for the independent AETHER Consensus Tape."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping

import sqlalchemy as sa
from fastapi import APIRouter, FastAPI, HTTPException

from aether_vnext.db_runtime import VNextDatabaseConfig, open_vnext_engine
from aether_vnext.freeze import LIVE_BLOCKED, PAPER_ONLY
from aether_vnext.store import VNextStore
from aether_vnext.tape_sources import tape_source_status


UTC = timezone.utc


def _stored_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def build_vnext_tape_snapshot(
    conn,
    *,
    store: VNextStore,
    as_of_utc: datetime,
    asset_limit: int = 500,
) -> dict[str, object]:
    if as_of_utc.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")
    if asset_limit < 1:
        raise ValueError("asset_limit must be positive")

    composites = store.tables["tape_composites"]
    rows = tuple(
        conn.execute(
            sa.select(composites)
            .order_by(
                composites.c.observed_at_utc.desc(),
                composites.c.composite_id.desc(),
            )
            .limit(asset_limit * 8)
        ).mappings()
    )
    latest: dict[str, Mapping[str, object]] = {}
    for row in rows:
        asset_id = str(row["asset_id"])
        if asset_id not in latest and len(latest) < asset_limit:
            latest[asset_id] = row

    assets: list[dict[str, object]] = []
    state_counts: dict[str, int] = {}
    accepted_total = 0
    rejected_total = 0
    for asset_id in sorted(latest):
        row = latest[asset_id]
        source_ids = tuple(str(value) for value in (row["source_observation_ids"] or ()))
        observations = store.load_tape_source_observations(
            conn,
            observation_ids=source_ids,
        )
        source_rows = []
        for observation in observations:
            current_age_ms = max(
                0,
                int(
                    (
                        as_of_utc
                        - _stored_utc(observation.received_ts)
                    ).total_seconds()
                    * 1000
                ),
            )
            source_rows.append(
                {
                    "observation_id": observation.observation_id,
                    "source_id": observation.source_id,
                    "venue": observation.venue,
                    "source_symbol": observation.source_symbol,
                    "contract_id": observation.contract_id,
                    "bid": observation.bid,
                    "ask": observation.ask,
                    "last": observation.last,
                    "mark": observation.mark,
                    "quality": observation.quality.value,
                    "exchange_ts": (
                        None
                        if observation.exchange_ts is None
                        else _stored_utc(observation.exchange_ts).isoformat()
                    ),
                    "received_ts": _stored_utc(observation.received_ts).isoformat(),
                    "current_age_ms": current_age_ms,
                    "source_data_version": observation.source_data_version,
                    "source_ref": observation.source_ref,
                }
            )

        state = str(row["state"])
        state_counts[state] = state_counts.get(state, 0) + 1
        accepted = tuple(str(value) for value in (row["accepted_source_ids"] or ()))
        rejected = tuple(str(value) for value in (row["rejected_source_ids"] or ()))
        accepted_total += len(accepted)
        rejected_total += len(rejected)
        assets.append(
            {
                "asset_id": asset_id,
                "state": state,
                "confidence": {
                    "FULL": "HIGH",
                    "DEGRADED": "MEDIUM",
                    "SINGLE_SOURCE": "LOW",
                    "CONTESTED": "CONTESTED",
                    "NOT_OBSERVED": "NONE",
                }.get(state, "NONE"),
                "composite_id": str(row["composite_id"]),
                "composite_mark": row["composite_mark"],
                "median_mark": row["median_mark"],
                "source_count": int(row["source_count"]),
                "quorum_required": int(row["quorum_required"]),
                "accepted_source_ids": list(accepted),
                "rejected_source_ids": list(rejected),
                "max_source_age_ms": row["max_source_age_ms"],
                "agreement_bps": row["agreement_bps"],
                "provenance_complete": bool(row["provenance_complete"]),
                "observed_at_utc": _stored_utc(row["observed_at_utc"]).isoformat(),
                "sources": sorted(source_rows, key=lambda item: str(item["source_id"])),
            }
        )

    return {
        "as_of_utc": as_of_utc.astimezone(UTC).isoformat(),
        "paper_only": bool(PAPER_ONLY),
        "live_blocked": bool(LIVE_BLOCKED),
        "authority": {
            "read_only_projection": True,
            "execution_permission": False,
            "execution_provider_independent": True,
        },
        "source_registry": list(tape_source_status()),
        "summary": {
            "asset_count": len(assets),
            "state_counts": dict(sorted(state_counts.items())),
            "accepted_source_count": accepted_total,
            "rejected_source_count": rejected_total,
        },
        "assets": assets,
    }


async def load_configured_vnext_tape_snapshot() -> dict[str, object]:
    try:
        config = VNextDatabaseConfig.from_environment()
    except ValueError as exc:
        raise HTTPException(
            status_code=503,
            detail="AETHER Tape unavailable: dedicated vNext database configuration is invalid",
        ) from exc

    try:
        async with open_vnext_engine(config) as engine:
            async with engine.connect() as connection:
                as_of_utc = datetime.now(UTC)

                def read(sync_conn):
                    return build_vnext_tape_snapshot(
                        sync_conn,
                        store=VNextStore(),
                        as_of_utc=as_of_utc,
                    )

                return await connection.run_sync(read)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="AETHER Tape unavailable: persisted Tape truth could not be read",
        ) from exc


def mount_configured_vnext_tape(app: FastAPI) -> None:
    router = APIRouter()

    @router.get("/api/v1/vnext/tape")
    async def read_vnext_tape() -> dict[str, object]:
        payload = await load_configured_vnext_tape_snapshot()
        if payload.get("paper_only") is not True or payload.get("live_blocked") is not True:
            raise RuntimeError("AETHER Tape safety invariant failed")
        return payload

    app.include_router(router)
