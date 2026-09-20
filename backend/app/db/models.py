"""Durable Aether ledger and configuration models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_order_id: Mapped[str] = mapped_column(String(96), unique=True, nullable=False)
    venue_order_id: Mapped[str | None] = mapped_column(String(128))
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(24), nullable=False, default="market")
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    reference_price: Mapped[float | None] = mapped_column(Float)
    limit_price: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    actor: Mapped[str] = mapped_column(String(32), nullable=False)
    paper_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_orders_created_at", "created_at"),
        Index("ix_orders_status", "status"),
    )


class Fill(Base):
    __tablename__ = "fills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_order_id: Mapped[str] = mapped_column(String(96), nullable=False)
    venue_fill_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    reference_price: Mapped[float] = mapped_column(Float, nullable=False)
    execution_price: Mapped[float] = mapped_column(Float, nullable=False)
    fee_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    spread_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    slippage_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    gross_pnl_usd: Mapped[float | None] = mapped_column(Float)
    net_pnl_usd: Mapped[float | None] = mapped_column(Float)
    paper_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_fills_client_order_id", "client_order_id"),
        Index("ix_fills_occurred_at", "occurred_at"),
    )


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    qty_open: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_entry: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    realized_session: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    daily_realized: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    peak_equity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class AccountSnapshot(Base):
    __tablename__ = "account_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    usd: Mapped[float] = mapped_column(Float, nullable=False)
    btc: Mapped[float] = mapped_column(Float, nullable=False)
    equity_usd: Mapped[float] = mapped_column(Float, nullable=False)
    mark: Mapped[float | None] = mapped_column(Float)
    open_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    realized_session: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    daily_realized: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    gross_realized: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    entry_fees_open: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_fees: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_spread_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_slippage_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index("ix_account_snapshots_captured_at", "captured_at"),)


class AuditEventRow(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    actor: Mapped[str] = mapped_column(String(32), nullable=False)
    component: Mapped[str] = mapped_column(String(48), nullable=False)
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_audit_events_ts_utc", "ts_utc"),
        Index("ix_audit_events_correlation_id", "correlation_id"),
        Index("ix_audit_events_event", "event"),
    )


class StrategyConfigRow(Base):
    __tablename__ = "strategy_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    config_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RiskConfigRow(Base):
    __tablename__ = "risk_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    config_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ReconcileEvent(Base):
    __tablename__ = "reconcile_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    local_btc: Mapped[float] = mapped_column(Float, nullable=False)
    venue_btc: Mapped[float] = mapped_column(Float, nullable=False)
    delta_btc: Mapped[float] = mapped_column(Float, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
