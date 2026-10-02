from __future__ import annotations

from datetime import datetime, timezone

import pytest
import sqlalchemy as sa

from aether_vnext.db_runtime import (
    VNextDatabaseConfig,
    normalize_async_database_url,
)
from aether_vnext.freeze import (
    CONFIGURATION_HASH,
    FREEZE_VERSION,
    canonical_freeze_payload,
)
from aether_vnext.policy_bootstrap import bootstrap_canonical_policy_snapshot
from aether_vnext.store import VNextStore


UTC = timezone.utc
NOW = datetime(2026, 9, 27, 0, 10, tzinfo=UTC)


def test_vnext_database_config_requires_dedicated_sandbox_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://legacy/production")
    monkeypatch.setenv(
        "AZURE_POSTGRESQL_CONNECTIONSTRING",
        "host=legacy database=prod user=legacy",
    )
    monkeypatch.delenv("AETHER_VNEXT_DATABASE_URL", raising=False)
    monkeypatch.delenv(
        "AETHER_VNEXT_AZURE_POSTGRESQL_CONNECTIONSTRING",
        raising=False,
    )
    monkeypatch.setenv("AETHER_VNEXT_ENVIRONMENT", "sandbox")

    with pytest.raises(ValueError, match="exactly one dedicated"):
        VNextDatabaseConfig.from_environment()


def test_vnext_database_config_rejects_non_sandbox_environment() -> None:
    with pytest.raises(ValueError, match="'sandbox'"):
        VNextDatabaseConfig(
            environment="production",
            database_url="postgresql://example/vnext",
        )


def test_vnext_database_config_rejects_ambiguous_connection_sources() -> None:
    with pytest.raises(ValueError, match="exactly one dedicated"):
        VNextDatabaseConfig(
            environment="sandbox",
            database_url="postgresql://example/vnext",
            azure_connection_string="host=x dbname=y user=z",
        )


def test_database_url_is_normalized_only_to_async_postgresql() -> None:
    assert (
        normalize_async_database_url("postgresql://u:p@host/db")
        == "postgresql+asyncpg://u:p@host/db"
    )
    assert (
        normalize_async_database_url("postgresql+asyncpg://u:p@host/db")
        == "postgresql+asyncpg://u:p@host/db"
    )
    with pytest.raises(ValueError, match="PostgreSQL"):
        normalize_async_database_url("sqlite:///tmp.db")


def test_canonical_policy_bootstrap_is_idempotent_and_exact() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        inserted = bootstrap_canonical_policy_snapshot(
            conn,
            store,
            effective_at_utc=NOW,
            created_at_utc=NOW,
        )
        again = bootstrap_canonical_policy_snapshot(
            conn,
            store,
            effective_at_utc=NOW,
            created_at_utc=NOW,
        )
        row = conn.execute(
            sa.select(store.tables["policy_snapshots"])
        ).mappings().one()

    assert inserted is True
    assert again is False
    assert row["configuration_hash"] == CONFIGURATION_HASH
    assert row["policy_version"] == FREEZE_VERSION
    assert row["payload"] == canonical_freeze_payload()
