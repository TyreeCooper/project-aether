"""GET-only operator-console projection for the isolated AETHER vNext prototype.

This surface exists for the vNext UI only. It reads the dedicated burn-in book,
returns current-epoch blotter/activity/ledger information, and never imports or
falls back to the legacy desk/runtime.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import date, datetime, timezone
from decimal import Decimal
import inspect
import hashlib
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, FastAPI, HTTPException

from aether_vnext.db_runtime import VNextDatabaseConfig, open_vnext_engine
from aether_vnext.freeze import LIVE_BLOCKED, PAPER_ONLY
from aether_vnext.store import SEED_LEDGER_CASH_USD, VNextStore


UTC = timezone.utc
OperatorSnapshotProvider = Callable[
    [], Mapping[str, object] | Awaitable[Mapping[str, object]]
]


def _stored_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return _stored_utc(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    return value


def _number(row: Mapping[str, Any], key: str) -> float:
    raw = row.get(key)
    return 0.0 if raw is None else float(raw)


def build_vnext_operator_snapshot(
    conn,
    *,
    store: VNextStore,
    as_of_utc: datetime,
) -> dict[str, object]:
    """Project current-epoch operator data without changing Firm state."""
    if as_of_utc.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")

    epoch = store.current_paper_test_epoch(conn)
    epoch_started = (
        None
        if epoch is None
        else _stored_utc(epoch["started_at_utc"])
    )

    blotter = store.closed_trades_current_paper_epoch(conn, limit=200)

    events = store.tables["event_ledger"]
    event_stmt = sa.select(events)
    if epoch_started is not None:
        event_stmt = event_stmt.where(
            events.c.created_at_utc >= epoch_started
        )
    event_rows = tuple(
        dict(row)
        for row in conn.execute(
            event_stmt.order_by(
                events.c.created_at_utc.desc(),
                events.c.event_id.desc(),
            ).limit(120)
        ).mappings()
    )

    ledgers = tuple(store.ledger_rows(conn))
    cash_available = sum(_number(row, "cash_available_usd") for row in ledgers)
    cash_reserved = sum(_number(row, "cash_reserved_usd") for row in ledgers)
    margin_used = sum(_number(row, "margin_used_usd") for row in ledgers)
    margin_available = sum(_number(row, "margin_available_usd") for row in ledgers)
    realized_pnl = sum(_number(row, "realized_pnl_usd") for row in ledgers)
    unrealized_pnl = sum(_number(row, "unrealized_pnl_usd") for row in ledgers)
    fees = sum(_number(row, "fees_accrued_usd") for row in ledgers)
    carry = sum(_number(row, "carry_accrued_usd") for row in ledgers)

    seed_bank = (
        float(sum(SEED_LEDGER_CASH_USD.values()))
        if epoch is None
        else float(epoch["seed_bank_total_usd"])
    )

    refresh_time = as_of_utc.astimezone(UTC).isoformat()
    snapshot_id = hashlib.sha256(refresh_time.encode("utf-8")).hexdigest()[:24]
    bound = epoch is not None or bool(ledgers)
    return {
        "snapshot_id": snapshot_id,
        "refresh_time_utc": refresh_time,
        "as_of_utc": refresh_time,
        "binding_state": "BOUND" if bound else "BASELINE_PENDING",
        "mode": {
            "paper_only": bool(PAPER_ONLY),
            "live_blocked": bool(LIVE_BLOCKED),
            "forced_entries_enabled": False,
            "natural_setups_only": True,
        },
        "authority": {
            "read_only_projection": True,
            "execution_permission": False,
            "may_mutate_firm_state": False,
            "legacy_fallback_allowed": False,
        },
        "paper_test": {
            "epoch_id": None if not bound or epoch is None else str(epoch["epoch_id"]),
            "started_at_utc": (
                None if epoch_started is None else epoch_started.isoformat()
            ),
            "seed_bank_usd": seed_bank if bound else None,
        },
        "bank": {
            "cash_available_usd": cash_available if bound else None,
            "cash_reserved_usd": (cash_reserved) if bound else None,
            "book_cash_usd": (cash_available + cash_reserved) if bound else None,
            "margin_used_usd": (margin_used) if bound else None,
            "margin_available_usd": (margin_available) if bound else None,
            "realized_pnl_usd": (realized_pnl) if bound else None,
            "unrealized_pnl_usd": (unrealized_pnl) if bound else None,
            "fees_accrued_usd": (fees) if bound else None,
            "carry_accrued_usd": (carry) if bound else None,
            "ledger_count": len(ledgers) if bound else None,
        },
        "blotter": [_json_safe(row) for row in blotter],
        "activity": [_json_safe(row) for row in event_rows],
        "ledgers": [_json_safe(row) for row in ledgers],
    }


async def load_configured_vnext_operator_snapshot() -> dict[str, object]:
    """Read the operator projection from the dedicated vNext burn-in database."""
    try:
        config = VNextDatabaseConfig.from_environment()
    except ValueError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "vNext operator console unavailable: dedicated burn-in "
                "database configuration is not valid"
            ),
        ) from exc

    try:
        async with open_vnext_engine(config) as engine:
            async with engine.connect() as conn:
                as_of_utc = datetime.now(UTC)

                def _read(sync_conn):
                    return build_vnext_operator_snapshot(
                        sync_conn,
                        store=VNextStore(),
                        as_of_utc=as_of_utc,
                    )

                return await conn.run_sync(_read)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "vNext operator console unavailable: dedicated burn-in "
                "book could not be read"
            ),
        ) from exc


def create_vnext_operator_router(
    snapshot_provider: OperatorSnapshotProvider,
) -> APIRouter:
    if not callable(snapshot_provider):
        raise ValueError("snapshot_provider must be callable")

    router = APIRouter()

    @router.get("/api/v1/vnext/operator")
    async def read_vnext_operator() -> dict[str, object]:
        result = snapshot_provider()
        snapshot = await result if inspect.isawaitable(result) else result
        if not isinstance(snapshot, Mapping):
            raise TypeError("snapshot_provider must return a mapping")
        payload = dict(snapshot)
        mode = dict(payload.get("mode") or {})
        if mode.get("paper_only") is not True or mode.get("live_blocked") is not True:
            raise RuntimeError("vNext operator snapshot safety invariant failed")
        return payload

    return router


def mount_configured_vnext_operator(app: FastAPI) -> None:
    if not isinstance(app, FastAPI):
        raise ValueError("app must be a FastAPI instance")
    app.include_router(
        create_vnext_operator_router(
            load_configured_vnext_operator_snapshot,
        )
    )
