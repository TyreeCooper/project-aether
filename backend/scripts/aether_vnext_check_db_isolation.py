"""Fail closed unless the configured target is isolated from legacy Aether tables."""
from __future__ import annotations

import asyncio
import json

from aether_vnext.db_isolation import require_isolated_burnin_database
from aether_vnext.db_runtime import open_vnext_engine


async def _main() -> None:
    async with open_vnext_engine() as engine:
        async with engine.connect() as connection:
            result = await connection.run_sync(require_isolated_burnin_database)
    print(
        json.dumps(
            {
                "database_name": result.database_name,
                "legacy_tables_found": list(result.legacy_tables_found),
                "vnext_schema_exists": result.vnext_schema_exists,
                "isolated": result.isolated,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    asyncio.run(_main())
