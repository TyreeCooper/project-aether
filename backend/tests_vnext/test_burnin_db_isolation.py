from __future__ import annotations

from dataclasses import dataclass

import pytest

from aether_vnext.db_isolation import (
    LEGACY_RUNTIME_PUBLIC_TABLES,
    require_isolated_burnin_database,
)


@dataclass
class _ScalarResult:
    value: object

    def scalar_one(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return list(self.value)


class _FakeConnection:
    def __init__(
        self,
        *,
        database_name: str,
        legacy_tables: tuple[str, ...],
        vnext_schema_exists: bool,
    ) -> None:
        self.database_name = database_name
        self.legacy_tables = legacy_tables
        self.vnext_schema_exists = vnext_schema_exists
        self.calls = 0

    def execute(self, statement):
        self.calls += 1
        sql = str(statement)
        if "current_database" in sql:
            return _ScalarResult(self.database_name)
        if "information_schema.tables" in sql:
            return _ScalarResult(self.legacy_tables)
        if "information_schema.schemata" in sql:
            return _ScalarResult(self.vnext_schema_exists)
        raise AssertionError(sql)


def test_isolation_guard_accepts_clean_dedicated_database() -> None:
    conn = _FakeConnection(
        database_name="aether_vnext_burnin",
        legacy_tables=(),
        vnext_schema_exists=False,
    )
    result = require_isolated_burnin_database(conn)
    assert result.isolated is True
    assert result.legacy_tables_found == ()
    assert result.database_name == "aether_vnext_burnin"


def test_isolation_guard_rejects_legacy_runtime_database() -> None:
    conn = _FakeConnection(
        database_name="aether",
        legacy_tables=("aether_runtime_state", "aether_fill"),
        vnext_schema_exists=False,
    )
    with pytest.raises(RuntimeError, match="legacy public tables found"):
        require_isolated_burnin_database(conn)


def test_guard_covers_all_known_legacy_runtime_table_families() -> None:
    required = {
        "aether_runtime_state",
        "aether_order",
        "aether_fill",
        "aether_account_snapshot",
        "aether_position_snapshot",
        "aether_asset_intelligence_snapshot",
        "aether_desk_trade",
    }
    assert required <= LEGACY_RUNTIME_PUBLIC_TABLES
