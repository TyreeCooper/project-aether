"""Read-only operator report for AETHER vNext burn-in readiness.

The command never migrates, bootstraps, binds providers, writes evidence, or starts a
campaign. It inspects the configured dedicated burn-in database and emits one report
covering isolation, schema completeness, seed-12 binding coverage, and canonical
Campaign #1 preflight status.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

import sqlalchemy as sa

from aether_vnext.burnin_readiness import (
    build_burnin_readiness,
    readiness_payload,
    runtime_book_blockers,
)
from aether_vnext.db_isolation import inspect_database_isolation
from aether_vnext.db_runtime import open_vnext_engine
from aether_vnext.forward_paper_preflight import (
    preflight_canonical_forward_paper_campaign_from_book,
)
from aether_vnext.store import VNextStore


def _emit(payload: dict[str, object], output: str | None) -> None:
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    print(rendered)
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")


async def _main(
    *,
    campaign_id: str,
    output: str | None,
) -> int:
    if not str(campaign_id).strip():
        raise ValueError("campaign_id is required")

    store = VNextStore(schema="aether_vnext")
    as_of_utc = datetime.now(timezone.utc)

    isolation = None
    actual_tables: tuple[str, ...] = ()
    runtime_asset_ids: tuple[str, ...] = ()
    preflight = None
    extra_blockers: list[str] = []

    async with open_vnext_engine() as engine:
        async with engine.connect() as connection:
            isolation = await connection.run_sync(inspect_database_isolation)

            if isolation.vnext_schema_exists:
                actual_tables = await connection.run_sync(
                    lambda sync_conn: tuple(
                        sorted(
                            sa.inspect(sync_conn).get_table_names(
                                schema="aether_vnext"
                            )
                        )
                    )
                )

            expected_tables = tuple(sorted(store.tables))
            missing_tables = tuple(
                sorted(set(expected_tables) - set(actual_tables))
            )
            if not isolation.vnext_schema_exists:
                extra_blockers.append("vnext_schema_missing")
            elif missing_tables:
                extra_blockers.append("vnext_schema_incomplete")
            else:
                rows = await connection.run_sync(
                    lambda sync_conn: store.list_runtime_registry_bindings(
                        sync_conn
                    )
                )
                runtime_asset_ids = tuple(
                    row["binding"].asset_id for row in rows
                )
                preflight = await connection.run_sync(
                    lambda sync_conn: (
                        preflight_canonical_forward_paper_campaign_from_book(
                            sync_conn,
                            store,
                            campaign_id=campaign_id,
                            as_of_utc=as_of_utc,
                        )
                    )
                )
                extra_blockers.extend(
                    await connection.run_sync(
                        lambda sync_conn: runtime_book_blockers(
                            sync_conn,
                            store=store,
                            as_of_utc=as_of_utc,
                        )
                    )
                )

    assert isolation is not None
    readiness = build_burnin_readiness(
        isolation=isolation,
        expected_schema_tables=tuple(sorted(store.tables)),
        actual_schema_tables=actual_tables,
        runtime_binding_asset_ids=runtime_asset_ids,
        preflight=preflight,
        extra_blockers=tuple(extra_blockers),
    )
    payload = readiness_payload(readiness)
    payload.update(
        {
            "campaign_id": campaign_id,
            "database_name": isolation.database_name,
            "legacy_tables_found": list(isolation.legacy_tables_found),
            "expected_schema_table_count": len(store.tables),
            "actual_schema_table_count": len(actual_tables),
            "checked_at_utc": as_of_utc.isoformat(),
        }
    )
    _emit(payload, output)
    return 0 if readiness.ready else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            _main(
                campaign_id=args.campaign_id,
                output=args.output,
            )
        )
    )
