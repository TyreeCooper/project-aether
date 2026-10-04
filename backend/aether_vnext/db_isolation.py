"""Read-only target-database isolation guard for AETHER vNext burn-in.

The guard runs before vNext migrations. Its purpose is to prevent a dedicated vNext
secret from accidentally pointing at the legacy Aether production database.
"""
from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.engine import Connection


LEGACY_RUNTIME_PUBLIC_TABLES = frozenset(
    {
        "aether_runtime_state",
        "aether_audit_event",
        "aether_order",
        "aether_fill",
        "aether_risk_event",
        "aether_account_snapshot",
        "aether_position_snapshot",
        "aether_bot_snapshot",
        "aether_asset_intelligence_snapshot",
        "aether_intelligence_observation",
        "aether_desk_trade",
    }
)


@dataclass(frozen=True, slots=True)
class DatabaseIsolationResult:
    database_name: str
    legacy_tables_found: tuple[str, ...]
    vnext_schema_exists: bool
    isolated: bool


def inspect_database_isolation(conn: Connection) -> DatabaseIsolationResult:
    database_name = str(conn.execute(sa.text("SELECT current_database()")).scalar_one())

    legacy_rows = conn.execute(
        sa.text(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN :legacy_names
            ORDER BY table_name
            """
        ).bindparams(
            sa.bindparam(
                "legacy_names",
                expanding=True,
                value=tuple(sorted(LEGACY_RUNTIME_PUBLIC_TABLES)),
            )
        )
    ).scalars().all()

    vnext_schema_exists = bool(
        conn.execute(
            sa.text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.schemata
                    WHERE schema_name = 'aether_vnext'
                )
                """
            )
        ).scalar_one()
    )

    found = tuple(str(name) for name in legacy_rows)
    return DatabaseIsolationResult(
        database_name=database_name,
        legacy_tables_found=found,
        vnext_schema_exists=vnext_schema_exists,
        isolated=not found,
    )


def require_isolated_burnin_database(conn: Connection) -> DatabaseIsolationResult:
    result = inspect_database_isolation(conn)
    if not result.isolated:
        joined = ",".join(result.legacy_tables_found)
        raise RuntimeError(
            "vNext burn-in database isolation failed; legacy public tables found: "
            + joined
        )
    return result
