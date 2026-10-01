"""Isolated database connection boundary for the AETHER vNext burn-in book.

vNext deliberately does not fall back to the legacy runtime's DATABASE_URL or
AZURE_POSTGRESQL_CONNECTIONSTRING variables. A non-production burn-in environment must
opt in with dedicated AETHER_VNEXT_* configuration.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import os
import shlex
from typing import AsyncIterator

from azure.identity import DefaultAzureCredential
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool


POSTGRES_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"
_ALLOWED_ENVIRONMENTS = frozenset({"burnin"})


def parse_connection_kv(raw: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for token in shlex.split(str(raw)):
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        values[key.strip().lower()] = value.strip()
    return values


def normalize_async_database_url(raw: str) -> str:
    value = str(raw).strip()
    if value.startswith("postgresql+asyncpg://"):
        return value
    if value.startswith("postgresql://"):
        return "postgresql+asyncpg://" + value.removeprefix("postgresql://")
    raise ValueError("vNext database URL must use PostgreSQL")


@dataclass(frozen=True, slots=True)
class VNextDatabaseConfig:
    environment: str
    database_url: str | None = None
    azure_connection_string: str | None = None

    def __post_init__(self) -> None:
        if self.environment not in _ALLOWED_ENVIRONMENTS:
            raise ValueError(
                "AETHER_VNEXT_ENVIRONMENT must be the isolated 'burnin' environment"
            )
        configured = int(bool(self.database_url)) + int(
            bool(self.azure_connection_string)
        )
        if configured != 1:
            raise ValueError(
                "configure exactly one dedicated vNext database connection"
            )

    @classmethod
    def from_environment(cls) -> "VNextDatabaseConfig":
        return cls(
            environment=os.getenv("AETHER_VNEXT_ENVIRONMENT", "").strip(),
            database_url=(
                os.getenv("AETHER_VNEXT_DATABASE_URL", "").strip() or None
            ),
            azure_connection_string=(
                os.getenv(
                    "AETHER_VNEXT_AZURE_POSTGRESQL_CONNECTIONSTRING",
                    "",
                ).strip()
                or None
            ),
        )


@asynccontextmanager
async def open_vnext_engine(
    config: VNextDatabaseConfig | None = None,
) -> AsyncIterator[AsyncEngine]:
    """Open the isolated vNext async SQLAlchemy engine and dispose it on exit."""
    cfg = config or VNextDatabaseConfig.from_environment()
    credential: DefaultAzureCredential | None = None

    if cfg.database_url:
        engine = create_async_engine(
            normalize_async_database_url(cfg.database_url),
            poolclass=NullPool,
            connect_args={
                "timeout": 8.0,
                "command_timeout": 12.0,
            },
        )
    else:
        assert cfg.azure_connection_string is not None
        values = parse_connection_kv(cfg.azure_connection_string)
        host = values.get("host")
        database = values.get("dbname") or values.get("database")
        user = values.get("user") or values.get("username")
        port = int(values.get("port", "5432"))
        if not host or not database or not user:
            raise RuntimeError(
                "vNext Azure PostgreSQL connection metadata is incomplete"
            )
        credential = DefaultAzureCredential(
            exclude_interactive_browser_credential=True
        )
        token = await asyncio.to_thread(
            credential.get_token,
            POSTGRES_SCOPE,
        )
        url = URL.create(
            "postgresql+asyncpg",
            username=user,
            password=token.token,
            host=host,
            port=port,
            database=database,
        )
        engine = create_async_engine(
            url,
            poolclass=NullPool,
            connect_args={
                "ssl": "require",
                "timeout": 8.0,
                "command_timeout": 12.0,
            },
        )

    try:
        yield engine
    finally:
        await engine.dispose()
        if credential is not None:
            await asyncio.to_thread(credential.close)
