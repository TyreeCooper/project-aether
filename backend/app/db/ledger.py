"""Async PostgreSQL persistence for paper/live-neutral ledger records."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from app.db.models import (
    AccountSnapshot,
    AuditEventRow,
    Fill,
    Order,
    Position,
    ReconcileEvent,
    ShadowDecision,
    VenueValidationEvent,
)
from app.db.session import async_session_factory


class LedgerRepository:
    """Best-effort durable ledger.

    Callers decide whether persistence is required for arming. In the current
    paper phase these methods return False on database failure instead of
    crashing the trading loop.
    """

    async def health(self) -> bool:
        """Return True only when the configured database accepts a round trip."""
        try:
            async with async_session_factory() as session:
                await session.execute(text("SELECT 1"))
            return True
        except SQLAlchemyError:
            return False

    async def record_order(self, order: dict[str, Any]) -> bool:
        try:
            async with async_session_factory() as session:
                session.add(
                    Order(
                        client_order_id=order["client_order_id"],
                        symbol=order["symbol"],
                        side=order["side"],
                        order_type="market",
                        qty=order["qty"],
                        reference_price=order.get("reference_price"),
                        status=order["status"],
                        actor=order["actor"],
                        paper_mode=bool(order.get("paper_mode", True)),
                        correlation_id=order["client_order_id"],
                    )
                )
                await session.commit()
            return True
        except SQLAlchemyError:
            return False

    async def record_fill(self, fill: dict[str, Any]) -> bool:
        try:
            async with async_session_factory() as session:
                session.add(
                    Fill(
                        client_order_id=fill["client_order_id"],
                        symbol=fill["symbol"],
                        side=fill["side"],
                        qty=fill["qty"],
                        reference_price=fill["reference_price"],
                        execution_price=fill["execution_price"],
                        fee_usd=fill["fee_usd"],
                        spread_cost_usd=fill["spread_cost_usd"],
                        slippage_cost_usd=fill["slippage_cost_usd"],
                        net_pnl_usd=fill.get("realized_net_pnl_usd"),
                        paper_mode=bool(fill.get("paper_mode", True)),
                    )
                )
                await session.commit()
            return True
        except SQLAlchemyError:
            return False

    async def save_portfolio(
        self,
        *,
        symbol: str,
        snapshot: dict[str, Any],
        entry_fees_open: float,
    ) -> bool:
        try:
            async with async_session_factory() as session:
                result = await session.execute(
                    select(Position).where(Position.symbol == symbol)
                )
                position = result.scalar_one_or_none()
                if position is None:
                    position = Position(symbol=symbol)
                    session.add(position)

                position.qty_open = float(snapshot["btc"])
                position.avg_entry = float(snapshot["avg_entry"])
                position.realized_session = float(snapshot["realized_session"])
                position.daily_realized = float(snapshot["daily_realized"])
                position.peak_equity = float(snapshot["peak_equity"])

                session.add(
                    AccountSnapshot(
                        usd=float(snapshot["usd"]),
                        btc=float(snapshot["btc"]),
                        equity_usd=float(snapshot["equity"]),
                        mark=snapshot.get("mark"),
                        open_pnl=float(snapshot["open_pnl"]),
                        realized_session=float(snapshot["realized_session"]),
                        daily_realized=float(snapshot["daily_realized"]),
                        gross_realized=float(snapshot["gross_realized"]),
                        entry_fees_open=float(entry_fees_open),
                        total_fees=float(snapshot["total_fees"]),
                        total_spread_cost=float(snapshot["total_spread_cost"]),
                        total_slippage_cost=float(snapshot["total_slippage_cost"]),
                        max_drawdown_pct=float(snapshot["max_drawdown_pct"]),
                    )
                )
                await session.commit()
            return True
        except SQLAlchemyError:
            return False

    async def record_audit(self, event: dict[str, Any]) -> bool:
        try:
            ts = datetime.fromisoformat(event["ts_utc"])
            async with async_session_factory() as session:
                session.add(
                    AuditEventRow(
                        ts_utc=ts,
                        level=event["level"],
                        actor=event["actor"],
                        component=event["component"],
                        event=event["event"],
                        correlation_id=event["correlation_id"],
                        message=event["message"],
                        payload=event.get("payload") or {},
                    )
                )
                await session.commit()
            return True
        except (SQLAlchemyError, ValueError, KeyError):
            return False

    async def load_latest_state(self, symbol: str) -> dict[str, Any] | None:
        try:
            async with async_session_factory() as session:
                snapshot_result = await session.execute(
                    select(AccountSnapshot)
                    .order_by(AccountSnapshot.captured_at.desc())
                    .limit(1)
                )
                account = snapshot_result.scalar_one_or_none()
                if account is None:
                    return None

                position_result = await session.execute(
                    select(Position).where(Position.symbol == symbol)
                )
                position = position_result.scalar_one_or_none()

                fill_result = await session.execute(
                    select(Fill)
                    .where(Fill.symbol == symbol)
                    .order_by(Fill.occurred_at.desc())
                    .limit(500)
                )
                fills = list(fill_result.scalars())

                order_result = await session.execute(
                    select(Order)
                    .where(Order.symbol == symbol)
                    .order_by(Order.created_at.desc())
                    .limit(500)
                )
                orders = list(order_result.scalars())

                return {
                    "account": account,
                    "position": position,
                    "fills": fills,
                    "orders": orders,
                }
        except SQLAlchemyError:
            return None


    async def record_reconcile(
        self,
        *,
        status: str,
        local_btc: float,
        venue_btc: float,
        delta_btc: float,
        note: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        try:
            async with async_session_factory() as session:
                session.add(
                    ReconcileEvent(
                        status=status,
                        local_btc=local_btc,
                        venue_btc=venue_btc,
                        delta_btc=delta_btc,
                        note=note,
                        payload=payload or {},
                    )
                )
                await session.commit()
            return True
        except SQLAlchemyError:
            return False


    async def record_validation_event(
        self,
        *,
        venue: str,
        client_order_id: str,
        symbol: str,
        side: str,
        qty: float,
        request_fingerprint: str,
        valid: bool,
        description: str | None,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        try:
            async with async_session_factory() as session:
                session.add(
                    VenueValidationEvent(
                        venue=venue,
                        client_order_id=client_order_id,
                        symbol=symbol,
                        side=side,
                        qty=qty,
                        request_fingerprint=request_fingerprint,
                        valid=valid,
                        description=description,
                        payload=payload or {},
                    )
                )
                await session.commit()
            return True
        except SQLAlchemyError:
            return False

    async def record_shadow_decision(
        self,
        *,
        symbol: str,
        signal: str,
        mark: float,
        qty: float,
        in_position: bool,
        would_execute: bool,
        reason: str,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        try:
            async with async_session_factory() as session:
                session.add(
                    ShadowDecision(
                        symbol=symbol,
                        signal=signal,
                        mark=mark,
                        qty=qty,
                        in_position=in_position,
                        would_execute=would_execute,
                        reason=reason,
                        payload=payload or {},
                    )
                )
                await session.commit()
            return True
        except SQLAlchemyError:
            return False
