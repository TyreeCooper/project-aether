"""Apply the AETHER vNext Alembic chain to the isolated burn-in database."""
from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config

from aether_vnext.db_runtime import open_vnext_engine


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _upgrade(sync_connection) -> None:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    cfg.attributes["connection"] = sync_connection
    command.upgrade(cfg, "head")


async def _main() -> None:
    async with open_vnext_engine() as engine:
        async with engine.begin() as connection:
            await connection.run_sync(_upgrade)


if __name__ == "__main__":
    asyncio.run(_main())
