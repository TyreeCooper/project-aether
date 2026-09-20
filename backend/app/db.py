"""PostgreSQL persistence for Project Aether.

Azure production uses the App Service system-assigned managed identity created by
Service Connector. Local development can opt in with DATABASE_URL.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shlex
from datetime import datetime, timezone
from typing import Any

import asyncpg
from azure.identity import DefaultAzureCredential

POSTGRES_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"


def parse_connection_kv(raw: str) -> dict[str, str]:
    """Parse the libpq-style string emitted by Azure Service Connector."""
    values: dict[str, str] = {}
    for token in shlex.split(raw):
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        values[key.strip().lower()] = value.strip()
    return values


def normalize_database_url(raw: str) -> str:
    if raw.startswith("postgresql+asyncpg://"):
        return "postgresql://" + raw.removeprefix("postgresql+asyncpg://")
    return raw


def _event_key(event: dict[str, Any]) -> str:
    existing = event.get("event_id")
    if existing:
        return str(existing)
    canonical = "|".join(
        (
            str(event.get("ts", "")),
            str(event.get("level", "")),
            str(event.get("message", "")),
        )
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _event_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return datetime.now(timezone.utc)


class DatabaseStore:
    def __init__(self) -> None:
        self.azure_connection_string = os.getenv(
            "AZURE_POSTGRESQL_CONNECTIONSTRING", ""
        ).strip()
        self.database_url = os.getenv("DATABASE_URL", "").strip()
        self.configured = bool(self.azure_connection_string or self.database_url)
        self.initialized = False
        self.last_error: str | None = None
        self.last_write_at: str | None = None
        self._credential: DefaultAzureCredential | None = None
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()

    @property
    def backend(self) -> str:
        if self.azure_connection_string:
            return "azure-postgresql-managed-identity"
        if self.database_url:
            return "postgresql-database-url"
        return "file-fallback"

    async def _connect(self) -> asyncpg.Connection:
        if self.azure_connection_string:
            values = parse_connection_kv(self.azure_connection_string)
            host = values.get("host")
            database = values.get("dbname") or values.get("database")
            user = values.get("user") or values.get("username")
            port = int(values.get("port", "5432"))
            if not host or not database or not user:
                raise RuntimeError(
                    "Azure PostgreSQL connection metadata is incomplete"
                )

            if self._credential is None:
                self._credential = DefaultAzureCredential(
                    exclude_interactive_browser_credential=True
                )
            token = await asyncio.to_thread(
                self._credential.get_token,
                POSTGRES_SCOPE,
            )
            return await asyncpg.connect(
                host=host,
                port=port,
                database=database,
                user=user,
                password=token.token,
                ssl="require",
                timeout=10,
                command_timeout=15,
                server_settings={"application_name": "project-aether"},
            )

        if self.database_url:
            return await asyncpg.connect(
                normalize_database_url(self.database_url),
                timeout=10,
                command_timeout=15,
                server_settings={"application_name": "project-aether"},
            )

        raise RuntimeError("PostgreSQL persistence is not configured")

    async def initialize(self) -> None:
        if not self.configured:
            return
        try:
            conn = await self._connect()
            try:
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS aether_runtime_state (
                        state_key TEXT PRIMARY KEY,
                        payload JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );

                    CREATE TABLE IF NOT EXISTS aether_audit_event (
                        event_key TEXT PRIMARY KEY,
                        ts TIMESTAMPTZ NOT NULL,
                        level TEXT NOT NULL,
                        message TEXT NOT NULL,
                        data JSONB,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );

                    CREATE TABLE IF NOT EXISTS aether_order (
                        execution_id TEXT PRIMARY KEY,
                        ts TIMESTAMPTZ NOT NULL,
                        actor TEXT NOT NULL,
                        side TEXT NOT NULL,
                        requested_qty_btc DOUBLE PRECISION NOT NULL,
                        status TEXT NOT NULL,
                        paper_mode BOOLEAN NOT NULL DEFAULT TRUE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );

                    CREATE TABLE IF NOT EXISTS aether_fill (
                        execution_id TEXT PRIMARY KEY,
                        ts TIMESTAMPTZ NOT NULL,
                        actor TEXT NOT NULL,
                        side TEXT NOT NULL,
                        qty_btc DOUBLE PRECISION NOT NULL,
                        price_usd DOUBLE PRECISION NOT NULL,
                        fee_usd DOUBLE PRECISION NOT NULL,
                        realized_pnl_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );

                    CREATE TABLE IF NOT EXISTS aether_risk_event (
                        event_key TEXT PRIMARY KEY,
                        ts TIMESTAMPTZ NOT NULL,
                        reason TEXT NOT NULL,
                        context JSONB,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );

                    CREATE TABLE IF NOT EXISTS aether_account_snapshot (
                        id BIGSERIAL PRIMARY KEY,
                        ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        usd DOUBLE PRECISION NOT NULL,
                        btc DOUBLE PRECISION NOT NULL,
                        equity DOUBLE PRECISION NOT NULL,
                        realized_session DOUBLE PRECISION NOT NULL,
                        daily_realized DOUBLE PRECISION NOT NULL,
                        peak_equity DOUBLE PRECISION NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS aether_position_snapshot (
                        id BIGSERIAL PRIMARY KEY,
                        ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        state TEXT NOT NULL,
                        btc DOUBLE PRECISION NOT NULL,
                        avg_entry DOUBLE PRECISION NOT NULL,
                        mark DOUBLE PRECISION,
                        open_pnl DOUBLE PRECISION NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS aether_bot_snapshot (
                        id BIGSERIAL PRIMARY KEY,
                        ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        state TEXT NOT NULL,
                        strategy TEXT NOT NULL,
                        short_ma INTEGER NOT NULL,
                        long_ma INTEGER NOT NULL,
                        stop_loss_pct DOUBLE PRECISION NOT NULL,
                        position_size_btc DOUBLE PRECISION NOT NULL,
                        max_position_btc DOUBLE PRECISION NOT NULL,
                        flatten_lock BOOLEAN NOT NULL
                    );
                    """
                )
            finally:
                await conn.close()
            self.initialized = True
            self.last_error = None
        except Exception as exc:
            self.initialized = False
            self.last_error = f"{type(exc).__name__}: {exc}"

    async def load_state(self) -> dict[str, Any] | None:
        if not self.initialized:
            return None
        try:
            conn = await self._connect()
            try:
                value = await conn.fetchval(
                    "SELECT payload FROM aether_runtime_state WHERE state_key = $1",
                    "paper",
                )
            finally:
                await conn.close()
            self.last_error = None
            if value is None:
                return None
            if isinstance(value, str):
                return json.loads(value)
            return dict(value)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None

    async def save_state(self, payload: dict[str, Any]) -> None:
        if not self.initialized:
            return
        async with self._lock:
            try:
                conn = await self._connect()
                try:
                    async with conn.transaction():
                        await conn.execute(
                            """
                            INSERT INTO aether_runtime_state
                                (state_key, payload, updated_at)
                            VALUES ($1, $2::jsonb, NOW())
                            ON CONFLICT (state_key)
                            DO UPDATE SET
                                payload = EXCLUDED.payload,
                                updated_at = NOW()
                            """,
                            "paper",
                            json.dumps(payload),
                        )

                        await conn.execute(
                            """
                            INSERT INTO aether_account_snapshot
                                (usd, btc, equity, realized_session,
                                 daily_realized, peak_equity)
                            VALUES ($1, $2, $3, $4, $5, $6)
                            """,
                            float(payload.get("usd", 0)),
                            float(payload.get("btc", 0)),
                            float(payload.get("equity", 0)),
                            float(payload.get("realized_session", 0)),
                            float(payload.get("daily_realized", 0)),
                            float(payload.get("peak_equity", 0)),
                        )

                        await conn.execute(
                            """
                            INSERT INTO aether_position_snapshot
                                (state, btc, avg_entry, mark, open_pnl)
                            VALUES ($1, $2, $3, $4, $5)
                            """,
                            str(payload.get("state", "OFFLINE")),
                            float(payload.get("btc", 0)),
                            float(payload.get("avg_entry", 0)),
                            (
                                float(payload["mark"])
                                if payload.get("mark") is not None
                                else None
                            ),
                            float(payload.get("open_pnl", 0)),
                        )

                        await conn.execute(
                            """
                            INSERT INTO aether_bot_snapshot
                                (state, strategy, short_ma, long_ma,
                                 stop_loss_pct, position_size_btc,
                                 max_position_btc, flatten_lock)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                            """,
                            str(payload.get("state", "OFFLINE")),
                            str(payload.get("strategy", "sma_crossover")),
                            int(payload.get("short_ma", 8)),
                            int(payload.get("long_ma", 21)),
                            float(payload.get("stop_loss_pct", 2)),
                            float(payload.get("position_size_btc", 0.01)),
                            float(payload.get("max_position_btc", 0.02)),
                            bool(payload.get("flatten_lock", False)),
                        )

                        for event in payload.get("audit") or []:
                            if not isinstance(event, dict):
                                continue
                            event_key = _event_key(event)
                            data = event.get("data")
                            await conn.execute(
                                """
                                INSERT INTO aether_audit_event
                                    (event_key, ts, level, message, data)
                                VALUES ($1, $2, $3, $4, $5::jsonb)
                                ON CONFLICT (event_key) DO NOTHING
                                """,
                                event_key,
                                _event_ts(event.get("ts")),
                                str(event.get("level", "INFO")),
                                str(event.get("message", "")),
                                (
                                    json.dumps(data)
                                    if data is not None
                                    else None
                                ),
                            )
                            if not isinstance(data, dict):
                                continue

                            kind = data.get("kind")
                            if kind == "order":
                                execution_id = str(
                                    data.get("execution_id") or event_key
                                )
                                await conn.execute(
                                    """
                                    INSERT INTO aether_order
                                        (execution_id, ts, actor, side,
                                         requested_qty_btc, status, paper_mode)
                                    VALUES ($1, $2, $3, $4, $5, $6, TRUE)
                                    ON CONFLICT (execution_id) DO NOTHING
                                    """,
                                    execution_id,
                                    _event_ts(event.get("ts")),
                                    str(data.get("actor", "unknown")),
                                    str(data.get("side", "unknown")),
                                    float(data.get("requested_qty_btc", 0)),
                                    str(data.get("status", "accepted")),
                                )
                            elif kind == "fill":
                                execution_id = str(
                                    data.get("execution_id") or event_key
                                )
                                await conn.execute(
                                    """
                                    INSERT INTO aether_fill
                                        (execution_id, ts, actor, side, qty_btc,
                                         price_usd, fee_usd, realized_pnl_usd)
                                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                                    ON CONFLICT (execution_id) DO NOTHING
                                    """,
                                    execution_id,
                                    _event_ts(event.get("ts")),
                                    str(data.get("actor", "unknown")),
                                    str(data.get("side", "unknown")),
                                    float(data.get("qty_btc", 0)),
                                    float(data.get("price_usd", 0)),
                                    float(data.get("fee_usd", 0)),
                                    float(data.get("realized_pnl_usd", 0)),
                                )
                            elif kind == "risk":
                                await conn.execute(
                                    """
                                    INSERT INTO aether_risk_event
                                        (event_key, ts, reason, context)
                                    VALUES ($1, $2, $3, $4::jsonb)
                                    ON CONFLICT (event_key) DO NOTHING
                                    """,
                                    event_key,
                                    _event_ts(event.get("ts")),
                                    str(data.get("reason", "unknown")),
                                    json.dumps(data),
                                )
                finally:
                    await conn.close()

                self.last_write_at = datetime.now(timezone.utc).isoformat()
                self.last_error = None
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"

    def schedule_save(self, payload: dict[str, Any]) -> None:
        if not self.initialized:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        safe_payload = json.loads(json.dumps(payload))
        task = loop.create_task(self.save_state(safe_payload))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def flush(self) -> None:
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def close(self) -> None:
        await self.flush()
        if self._credential is not None:
            await asyncio.to_thread(self._credential.close)

    def status(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "initialized": self.initialized,
            "backend": self.backend,
            "last_write_at": self.last_write_at,
            "last_error": self.last_error,
        }


db_store = DatabaseStore()
