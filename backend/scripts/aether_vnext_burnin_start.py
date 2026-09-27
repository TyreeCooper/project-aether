"""Canonical Campaign #1 start CLI for AETHER vNext forward-paper burn-in."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from aether_vnext.db_runtime import open_vnext_engine
from aether_vnext.forward_paper_start import (
    start_forward_paper_campaign_from_book,
)
from aether_vnext.store import VNextStore


def _serialize(result) -> dict[str, object]:
    return {
        "campaign_id": result.campaign.campaign_id,
        "configuration_hash": result.campaign.configuration_hash,
        "policy_version": result.campaign.policy_version,
        "baseline_snapshot_hash": result.baseline_snapshot_hash,
        "started_at_utc": result.campaign.started_at_utc.isoformat(),
        "created_at_utc": result.campaign.created_at_utc.isoformat(),
        "route_count": len(result.routes),
        "forced_entry_enabled": result.campaign.forced_entry_enabled,
        "natural_setup_only": result.campaign.natural_setup_only,
        "no_cherry_pick": result.campaign.no_cherry_pick,
        "live_blocked": result.campaign.live_blocked,
        "routes": [
            {
                "campaign_route_id": row.campaign_route_id,
                "route_id": row.route_id,
                "playbook_id": row.playbook_id,
                "playbook_version": row.playbook_version,
                "historical_validation_window_ids": list(
                    row.historical_validation_window_ids
                ),
                "historical_metrics_snapshot_hash": (
                    row.historical_metrics_snapshot_hash
                ),
            }
            for row in result.routes
        ],
    }


def _emit_report(payload: dict[str, object], output: str | None) -> None:
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    print(rendered)
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")


async def _main(campaign_id: str, output: str | None) -> int:
    store = VNextStore(schema="aether_vnext")
    now = datetime.now(timezone.utc)
    async with open_vnext_engine() as engine:
        async with engine.begin() as connection:
            result = await connection.run_sync(
                lambda sync_conn: start_forward_paper_campaign_from_book(
                    sync_conn,
                    store,
                    campaign_id=campaign_id,
                    started_at_utc=now,
                    created_at_utc=now,
                )
            )
    _emit_report(_serialize(result), output)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main(args.campaign_id, args.output)))
