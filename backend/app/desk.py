"""Aether multi-market paper desk: one risk account, twelve tailored books."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import os
import time
import uuid
from typing import Any

from app import live, venue
from app.asset_sources import merge_source_registry, registry_summary, set_trust_state
from app.community import fetch_reddit
from app.crypto_events import fetch_crypto_calendar
from app.db import db_store
from app.intelligence import asset_context, floor_intelligence
from app.news import fetch_asset_news
from app.official_macro import verify_macro_events
from app.desk_persist import load_desk, save_desk
from app.events import active_risk, fetch_calendar
from app.execution_matrix import (
    capability_cells,
    clock_horizon,
    directional_summary,
    execution_mode,
    supported_horizons,
)
from app.horizons import TradingHorizon
from app.playbooks import playbook_profile
from app.routing import PaperStrategyRouter
from app.universe import ASSETS, export_assets, register_asset
from app.wallet import STARTING_USD
from app.paper_portfolio import PaperPortfolio
from app.pair_book import PairBook

logger = logging.getLogger("aether.desk")
RISK_SLICE = 0.08
TRADE_RISK_FRACTION = 0.0075
MAX_ACTIVE_POSITIONS = 4
POLL = 20


def completed_bars(
    rows: list[dict[str, Any]],
    interval_seconds: int,
    *,
    now_ts: int | None = None,
) -> list[dict[str, Any]]:
    """Return only candles whose full interval has elapsed."""
    if not rows:
        return []
    now = int(time.time()) if now_ts is None else int(now_ts)
    last_ts = int(rows[-1].get("ts") or 0)
    if last_ts > 0 and last_ts + int(interval_seconds) > now:
        return rows[:-1]
    return rows


class MultiDesk:
    def __init__(self, execution_test_mode: bool = False) -> None:
        restored = load_desk()
        if isinstance(restored, dict):
            for asset in restored.get("assets") or []:
                if isinstance(asset, dict):
                    try:
                        register_asset(asset)
                    except (KeyError, TypeError, ValueError):
                        continue
        self.wallet = PaperPortfolio(STARTING_USD)
        self.books = [PairBook(asset, self.wallet) for asset in ASSETS]
        self.by_id = {b.id: b for b in self.books}
        self._task: asyncio.Task | None = None
        self.execution_test_mode = bool(execution_test_mode)
        self.strategy_router = PaperStrategyRouter()
        self.armed = os.getenv("AETHER_AUTO_RUN", "1").strip() not in {"0", "false", "FALSE"}
        self.risk_slice = max(
            0.01,
            min(float(os.getenv("AETHER_RISK_SLICE", str(RISK_SLICE))), 0.25),
        )
        self.poll_seconds = max(
            5,
            min(int(os.getenv("AETHER_DESK_POLL_SECONDS", str(POLL))), 120),
        )
        self.live_blocked = True
        self._last_market_success = 0.0
        self._last_market_error: str | None = None
        self._last_context_refresh = 0.0
        self._last_daily_refresh = 0.0
        self.risk_events: list[dict[str, Any]] = []
        self.risk_calendar_connected = False
        self.official_macro_sources: dict[str, dict[str, Any]] = {
            "bls": {"connected": False, "status": "unavailable"},
            "federal_reserve": {"connected": False, "status": "planned"},
            "bea": {"connected": False, "status": "planned"},
        }
        self._last_risk_refresh = 0.0
        self.crypto_events: list[dict[str, Any]] = []
        self.crypto_calendar_connected = False
        self.crypto_calendar_configured = False
        self.crypto_calendar_status = "unconfigured"
        self._last_crypto_refresh = 0.0
        self.community_cache: dict[str, dict[str, Any]] = {}
        self._community_cursor = 0
        self._last_community_refresh = 0.0
        self.news_cache: dict[str, dict[str, Any]] = {}
        self._news_cursor = 0
        self._last_news_refresh = 0.0
        self._last_intelligence_persist = 0.0
        self.activity_events: list[dict[str, Any]] = []
        restored_sources = (
            restored.get("asset_source_registry")
            if isinstance(restored, dict)
            else None
        )
        self.asset_source_registry = merge_source_registry(
            restored_sources if isinstance(restored_sources, list) else [],
            [book.id for book in self.books],
        )
        self._restore(restored)

    def marks(self) -> dict[str, float]:
        return {b.id: float(b.mark or 0.0) for b in self.books}

    def _latest_closed_minute_ts(self) -> int | None:
        latest: list[int] = []
        now = int(time.time())
        for book in self.books:
            rows = completed_bars(
                list(book.bars),
                60,
                now_ts=now,
            )
            if rows:
                ts = int(rows[-1].get("ts") or 0)
                if ts > 0:
                    latest.append(ts)
        return max(latest) if latest else None

    def _btc_gate(self) -> tuple[bool, bool]:
        btc = self.by_id.get("btc")
        if btc is None:
            return False, False
        btc_long = btc.qty() > 0
        try:
            btc_bias = btc.snapshot_strategy().get("direction") == "long"
        except Exception:
            btc_bias = False
        return bool(btc_bias), bool(btc_long)

    def persist(self) -> None:
        books = {}
        for book in self.books:
            books[book.id] = {
                "stop": book.stop,
                "highest": book.highest,
                "lowest": book.lowest,
                "entry_at": book.entry_at,
                "entry_mode": book.entry_mode,
                "last_entry_signal_key": book.last_entry_signal_key,
                "last_reason": book.last_reason,
                "fills": list(book.fills)[-200:],
            }
        save_desk(
            {
                "wallet": self.wallet.payload(),
                "assets": export_assets(),
                "books": books,
                "armed": self.armed,
                "settings": {
                    "risk_slice": self.risk_slice,
                    "poll_seconds": self.poll_seconds,
                },
                "asset_source_registry": self.asset_source_registry,
                "activity_events": self.activity_events[-300:],
                "strategy_route_buckets": {
                    horizon.value: int(bucket)
                    for horizon, bucket in (
                        self.strategy_router.clock.last_bucket.items()
                    )
                },
                "saved_at": time.time(),
            }
        )

    def _restore(self, data: dict[str, Any] | None = None) -> None:
        data = data if data is not None else load_desk()
        if not data:
            return
        wallet = data.get("wallet")
        if isinstance(wallet, dict) and "usd" in wallet:
            self.wallet.restore(wallet)
        rows = data.get("books") or {}
        if isinstance(rows, dict):
            for asset_id, row in rows.items():
                book = self.by_id.get(str(asset_id))
                if not book or not isinstance(row, dict):
                    continue
                book.stop = float(row.get("stop") or 0)
                book.highest = float(row.get("highest") or 0)
                book.lowest = float(row.get("lowest") or 0)
                book.entry_at = row.get("entry_at")
                book.entry_mode = row.get("entry_mode")
                book.last_entry_signal_key = row.get("last_entry_signal_key")
                book.last_reason = str(row.get("last_reason") or book.last_reason)
                fills = row.get("fills") or []
                if isinstance(fills, list):
                    book.fills = [f for f in fills[-200:] if isinstance(f, dict)]
        for book in self.books:
            position = self.wallet.position(book.id)
            if not position:
                continue

            # Legacy SpotWallet migrations may have preserved the original
            # book entry timestamp even though the migrated portfolio position
            # has opened_at=None. Promote that known timestamp into the
            # canonical position rather than inventing a new trade start time.
            if not position.get("opened_at") and book.entry_at:
                stored_position = self.wallet.positions.get(book.id)
                if stored_position is not None:
                    stored_position["opened_at"] = book.entry_at
                    position["opened_at"] = book.entry_at

            book.entry_at = (
                book.entry_at
                or position.get("opened_at")
            )
            book.entry_mode = (
                book.entry_mode
                or position.get("mode")
            )
            book.last_entry_signal_key = (
                book.last_entry_signal_key
                or position.get("signal_key")
            )
            if not book.stop:
                book.stop = float(
                    position.get("current_stop")
                    or position.get("initial_stop")
                    or 0.0
                )
            entry = float(position.get("entry_price") or 0.0)
            if entry > 0:
                book.highest = book.highest or entry
                book.lowest = book.lowest or entry

        activity = data.get("activity_events") or []
        if isinstance(activity, list):
            self.activity_events = [
                dict(row)
                for row in activity[-300:]
                if isinstance(row, dict)
            ]

        route_buckets = data.get("strategy_route_buckets") or {}
        if isinstance(route_buckets, dict):
            for raw_horizon, raw_bucket in route_buckets.items():
                try:
                    horizon = TradingHorizon(str(raw_horizon))
                    self.strategy_router.clock.last_bucket[horizon] = int(
                        raw_bucket
                    )
                except (TypeError, ValueError):
                    continue

        if "armed" in data:
            self.armed = bool(data["armed"])
        settings = data.get("settings") or {}
        if isinstance(settings, dict):
            try:
                self.risk_slice = max(
                    0.01,
                    min(float(settings.get("risk_slice", self.risk_slice)), 0.25),
                )
            except (TypeError, ValueError):
                pass
            try:
                self.poll_seconds = max(
                    5,
                    min(int(settings.get("poll_seconds", self.poll_seconds)), 120),
                )
            except (TypeError, ValueError):
                pass
        logger.info(
            "desk restored usd=%.4f holdings=%s",
            self.wallet.usd,
            list(self.wallet.units),
        )

    def snapshot(self) -> dict[str, Any]:
        wallet = self.wallet.snapshot(self.marks())
        return {
            "wallet": wallet,
            "books": [b.view() for b in self.books],
            "armed": self.armed,
            "live": live.status(),
            "live_blocked": True,
            "model": "multi_market_paper_portfolio",
            "persists": True,
        }

    def engine_status(self) -> dict[str, Any]:
        running = bool(self._task and not self._task.done())
        return {
            "armed": bool(self.armed),
            "running": running,
            "accepting_entries": bool(self.armed and running),
            "live_blocked": True,
            "source": "multi_asset_desk",
            "execution_test_mode": self.execution_test_mode,
        }

    def execution_matrix_snapshot(self) -> dict[str, Any]:
        return {
            "load": "AETHER-LOAD-002",
            "mode": "paper_execution_experiment",
            **directional_summary(),
            "cells": capability_cells(),
        }

    def settings_snapshot(self) -> dict[str, Any]:
        return {
            "allocation_per_entry_pct": round(self.risk_slice * 100, 2),
            "quote_poll_seconds": int(self.poll_seconds),
            "resume_armed_after_restart": True,
            "state_persistence": True,
            "execution_test_mode": self.execution_test_mode,
            "execution_test_load": "AETHER-LOAD-002" if self.execution_test_mode else None,
        }

    async def initialize_history_persistence(self) -> None:
        """Backfill any file-restored closed trades into durable PostgreSQL."""
        if not db_store.initialized:
            return
        rows = self.blotter(5000)
        if rows:
            ok = await db_store.save_desk_trades(rows)
            if not ok and db_store.last_error:
                logger.warning(
                    "desk trade-history backfill failed %s",
                    db_store.last_error,
                )

    @staticmethod
    def _age_seconds(timestamp: float, now: float) -> float | None:
        return round(now - timestamp, 2) if timestamp > 0 else None

    def intelligence_health_snapshot(self) -> dict[str, Any]:
        now = time.time()
        market_age = self._age_seconds(self._last_market_success, now)
        market_state = (
            "offline"
            if self._last_market_success <= 0 and self._last_market_error
            else "unavailable"
            if self._last_market_success <= 0
            else "stale"
            if market_age is not None
            and market_age > max(self.poll_seconds * 3, 180)
            else "healthy"
        )

        def rotating_feed(
            cache: dict[str, dict[str, Any]],
            per_asset_seconds: int,
        ) -> dict[str, Any]:
            expected = max(len(self.books), 1)
            coverage = len(cache) / expected
            fetched = [
                float(row.get("fetched_at") or 0)
                for row in cache.values()
                if float(row.get("fetched_at") or 0) > 0
            ]
            oldest_age = (
                max(now - value for value in fetched)
                if fetched
                else None
            )
            cycle = per_asset_seconds * expected
            degraded = any(
                str(row.get("status") or "") == "degraded"
                for row in cache.values()
            )
            if degraded:
                state = "degraded"
            elif coverage < 1:
                state = "partial" if cache else "unavailable"
            elif oldest_age is not None and oldest_age > cycle * 2.5:
                state = "stale"
            else:
                state = "healthy"
            return {
                "state": state,
                "coverage_pct": round(min(coverage, 1.0) * 100, 2),
                "oldest_age_seconds": (
                    None if oldest_age is None else round(oldest_age, 2)
                ),
                "expected_cycle_seconds": cycle,
            }

        macro_age = self._age_seconds(self._last_risk_refresh, now)
        macro_state = (
            "healthy"
            if self.risk_calendar_connected
            and macro_age is not None
            and macro_age <= 900
            else "stale"
            if self.risk_calendar_connected
            else "degraded"
        )
        crypto_age = self._age_seconds(self._last_crypto_refresh, now)
        crypto_state = (
            "unconfigured"
            if not self.crypto_calendar_configured
            else "healthy"
            if self.crypto_calendar_connected
            and crypto_age is not None
            and crypto_age <= 2700
            else "stale"
            if self.crypto_calendar_connected
            else "degraded"
        )
        return {
            "market": {
                "state": market_state,
                "last_success_age_seconds": market_age,
                "last_error": self._last_market_error,
            },
            "macro_calendar": {
                "state": macro_state,
                "last_refresh_age_seconds": macro_age,
            },
            "crypto_calendar": {
                "state": crypto_state,
                "last_refresh_age_seconds": crypto_age,
            },
            "news": rotating_feed(self.news_cache, 45),
            "community": rotating_feed(self.community_cache, 30),
            "official_macro": self.official_macro_sources,
            "note": "Unavailable, partial, degraded, stale, and healthy are distinct states.",
        }

    @staticmethod
    def _duration_seconds(
        opened_at: str | None,
        closed_at: str | None = None,
    ) -> int | None:
        if not opened_at:
            return None
        try:
            opened = datetime.fromisoformat(
                str(opened_at).replace("Z", "+00:00")
            )
            closed = (
                datetime.fromisoformat(
                    str(closed_at).replace("Z", "+00:00")
                )
                if closed_at
                else datetime.now(timezone.utc)
            )
        except ValueError:
            return None
        return max(int((closed - opened).total_seconds()), 0)

    def _record_event(
        self,
        event_type: str,
        book: PairBook,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = {
            "event_id": uuid.uuid4().hex,
            "event_type": str(event_type),
            "ts": datetime.now(timezone.utc).isoformat(),
            "asset_id": book.id,
            "symbol": book.symbol,
            "pair": book.pair,
            "broker": book.broker,
            **dict(payload or {}),
        }
        self.activity_events.append(row)
        self.activity_events = self.activity_events[-300:]
        return row

    def live_trades(self) -> dict[str, Any]:
        btc_bias, btc_long = self._btc_gate()
        items: list[dict[str, Any]] = []
        watch: list[dict[str, Any]] = []

        for book in self.books:
            position = self.wallet.position(book.id)
            if position:
                mark = float(
                    book.mark
                    or position.get("entry_price")
                    or 0.0
                )
                notional = self.wallet.notional_usd(
                    book.id,
                    mark,
                )
                open_pnl = self.wallet.open_pnl(
                    book.id,
                    mark,
                )
                try:
                    strategy = book.snapshot_strategy(
                        btc_bias_on=btc_bias,
                        btc_in_position=btc_long,
                    )
                except Exception as exc:
                    strategy = {
                        "reason": f"strategy_error:{exc}",
                    }
                excursion = book.current_excursion()
                entry = float(
                    position.get("entry_price") or 0.0
                )
                side = str(position.get("side") or "long")
                move = (
                    ((mark / entry) - 1) * 100
                    if side == "long" and entry > 0
                    else ((entry / mark) - 1) * 100
                    if side == "short" and mark > 0
                    else 0.0
                )
                opened_at = position.get("opened_at") or book.entry_at
                items.append(
                    {
                        "trade_id": position.get("trade_id"),
                        "asset_id": book.id,
                        "symbol": book.symbol,
                        "pair": book.pair,
                        "broker": book.broker,
                        "product_type": position.get(
                            "product_type"
                        ),
                        "side": side,
                        "mode": position.get("mode"),
                        "opened_at": opened_at,
                        "duration_seconds": self._duration_seconds(
                            opened_at
                        ),
                        "entry_price": entry,
                        "current_price": mark,
                        "stop_price": book.stop or position.get(
                            "current_stop"
                        ),
                        "quantity": position.get("quantity"),
                        "quantity_unit": position.get(
                            "quantity_unit"
                        ),
                        "notional_usd": round(notional, 4),
                        "margin_reserved_usd": position.get(
                            "margin_reserved_usd"
                        ),
                        "open_pnl_usd": round(open_pnl, 4),
                        "price_move_pct": round(move, 4),
                        "mfe_pct": excursion.get("mfe_pct"),
                        "mae_pct": excursion.get("mae_pct"),
                        "entry_reason": (
                            position.get("metadata") or {}
                        ).get("entry_reason"),
                        "quality_score": (
                            position.get("metadata") or {}
                        ).get("quality_score"),
                        "entry_clock": (
                            position.get("metadata") or {}
                        ).get("entry_clock"),
                        "bias_clock": (
                            position.get("metadata") or {}
                        ).get("bias_clock"),
                        "execution_test": bool(
                            position.get("execution_test_funded")
                            or (position.get("metadata") or {}).get(
                                "execution_test"
                            )
                        ),
                        "execution_test_load": (
                            position.get("metadata") or {}
                        ).get("execution_test_load"),
                        "would_have_blocked_by": (
                            position.get("metadata") or {}
                        ).get("would_have_blocked_by"),
                        "normal_execution_status": (
                            position.get("metadata") or {}
                        ).get("normal_execution_status"),
                        "normal_signal": (
                            position.get("metadata") or {}
                        ).get("normal_signal"),
                        "normal_quality_score": (
                            position.get("metadata") or {}
                        ).get("normal_quality_score"),
                        "routing_horizon": (
                            position.get("metadata") or {}
                        ).get("routing_horizon"),
                        "clock_horizon": (
                            position.get("metadata") or {}
                        ).get("clock_horizon"),
                        "strategy_id": (
                            position.get("metadata") or {}
                        ).get("strategy_id"),
                        "strategy_version": (
                            position.get("metadata") or {}
                        ).get("strategy_version"),
                        "management_state": (
                            "EXIT WATCH"
                            if strategy.get("exit_signal")
                            else "MANAGING"
                        ),
                        "strategy": {
                            "reason": strategy.get("reason"),
                            "direction": strategy.get("direction"),
                            "daily_grain": strategy.get(
                                "daily_grain"
                            ),
                            "four_hour_grain": strategy.get(
                                "four_hour_grain"
                            ),
                            "one_hour_grain": strategy.get(
                                "one_hour_grain"
                            ),
                            "signal": strategy.get("signal"),
                        },
                    }
                )
                continue

            try:
                snap = book.snapshot_strategy(
                    btc_bias_on=btc_bias,
                    btc_in_position=btc_long,
                )
            except Exception:
                continue
            watch.append(
                {
                    "asset_id": book.id,
                    "symbol": book.symbol,
                    "pair": book.pair,
                    "mode": snap.get("mode"),
                    "signal": snap.get("signal"),
                    "direction": snap.get("direction"),
                    "reason": snap.get("reason"),
                    "quality_score": int(
                        snap.get("quality_score") or 0
                    ),
                    "execution_status": snap.get(
                        "execution_status"
                    ),
                }
            )

        watch.sort(
            key=lambda row: int(row.get("quality_score") or 0),
            reverse=True,
        )
        items.sort(
            key=lambda row: str(row.get("opened_at") or "")
        )
        return {
            "state": "trading" if items else "scanning",
            "open_count": len(items),
            "items": items,
            "watch": watch[:5],
            "events": self.trade_events(40),
        }

    def trade_events(
        self,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        rows = list(self.activity_events)
        rows.sort(
            key=lambda row: str(row.get("ts") or ""),
            reverse=True,
        )
        return rows[: max(1, int(limit))]

    def source_registry_snapshot(self) -> dict[str, Any]:
        return {
            "items": [dict(row) for row in self.asset_source_registry],
            "summary": registry_summary(self.asset_source_registry),
        }

    def update_source_trust(
        self,
        source_id: str,
        state: str,
    ) -> dict[str, Any]:
        self.asset_source_registry = set_trust_state(
            self.asset_source_registry,
            source_id,
            state,
        )
        self.persist()
        return self.source_registry_snapshot()

    def update_settings(
        self,
        *,
        allocation_per_entry_pct: float,
        quote_poll_seconds: int,
    ) -> dict[str, Any]:
        self.risk_slice = max(0.01, min(float(allocation_per_entry_pct) / 100.0, 0.25))
        self.poll_seconds = max(5, min(int(quote_poll_seconds), 120))
        self.persist()
        return self.settings_snapshot()

    def floor_snapshot(self) -> dict[str, Any]:
        marks = self.marks()
        wallet = self.wallet.snapshot(marks)
        rows: list[dict[str, Any]] = []
        realized = fees = open_pnl = invested = 0.0
        trades = wins = losses = 0
        for book in self.books:
            view = book.view()
            stats = book.analytics()
            view["analytics"] = stats
            view["intelligence"] = asset_context(
                book,
                self.books,
                events=self.risk_events,
                calendar_connected=self.risk_calendar_connected,
                community=self.community_cache.get(book.id),
                news=self.news_cache.get(book.id),
            )
            rows.append(view)
            realized += float(stats["realized_pnl"])
            fees += float(stats["fees"])
            open_pnl += float(view["open_pnl"])
            invested += float(view["position_value"])
            trades += int(stats["trades"])
            wins += int(stats["wins"])
            losses += int(stats["losses"])
        equity = float(wallet["equity"])
        engine_status = self.engine_status()
        return {
            "strategy_name": "Aether Vector Engine",
            "strategy_internal": "asset_class_grain_playbooks_v1",
            "armed": engine_status["armed"],
            "running": engine_status["running"],
            "accepting_entries": engine_status["accepting_entries"],
            "engine": engine_status,
            "live_blocked": True,
            "model": "multi_market_paper_portfolio",
            "portfolio": {
                "equity": round(equity, 4),
                "starting_bank": round(float(wallet.get("starting_usd") or STARTING_USD), 4),
                "cash": round(float(wallet["usd"]), 4),
                "free_margin": round(float(wallet.get("free_margin_usd") or 0.0), 4),
                "available_buying_power": round(float(wallet.get("available_buying_power_usd") or 0.0), 4),
                "margin_used": round(float(wallet.get("reserved_margin_usd") or 0.0), 4),
                "gross_exposure": round(float(wallet.get("gross_exposure_usd") or 0.0), 4),
                "test_overflow": round(float(wallet.get("test_overflow_usd") or 0.0), 4),
                "invested": round(invested, 4),
                "open_pnl": round(open_pnl, 4),
                "realized_pnl": round(realized, 4),
                "total_pnl": round(open_pnl + realized, 4),
                "fees": round(fees, 4),
                "exposure_pct": round(invested / equity * 100, 2) if equity > 0 else 0.0,
                "active_positions": sum(1 for row in rows if float(row["qty"]) > 0),
                "assets": len(rows),
                "trades": trades,
                "wins": wins,
                "losses": losses,
                "win_rate_pct": round(wins / max(wins + losses, 1) * 100, 2),
            },
            "assets": rows,
            "intelligence": floor_intelligence(
                self.books,
                events=self.risk_events,
                calendar_connected=self.risk_calendar_connected,
                community_cache=self.community_cache,
                news_cache=self.news_cache,
                crypto_calendar_connected=self.crypto_calendar_connected,
                crypto_calendar_configured=self.crypto_calendar_configured,
                bls_connected=bool(
                    (self.official_macro_sources.get("bls") or {}).get("connected")
                ),
            ),
            "risk_calendar": self.risk_snapshot(),
        }

    def asset_snapshot(self, asset_id: str) -> dict[str, Any] | None:
        book = self.by_id.get(str(asset_id).lower())
        if not book:
            return None
        view = book.view()
        stats = book.analytics()
        btc_bias, btc_long = self._btc_gate()
        try:
            strategy = book.snapshot_strategy(
                btc_bias_on=btc_bias,
                btc_in_position=btc_long,
            )
        except Exception as exc:
            strategy = {"signal": None, "reason": f"strategy_error:{exc}"}
        bars = list(book.bars)
        series = [
            {
                "ts": int(row["ts"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }
            for row in bars[-240:]
        ]
        recent = bars[-240:]
        high = max((float(x["high"]) for x in recent), default=float(book.mark or 0))
        low = min((float(x["low"]) for x in recent), default=float(book.mark or 0))
        return {
            "strategy_name": "Aether Vector Engine",
            "live_blocked": True,
            "armed": self.armed,
            "asset": view,
            "analytics": stats,
            "strategy": strategy,
            "series": series,
            "window": {
                "bars": len(recent),
                "high": high,
                "low": low,
            },
            "fills": list(book.fills)[-50:],
            "intelligence": asset_context(
                book,
                self.books,
                events=self.risk_events,
                calendar_connected=self.risk_calendar_connected,
                community=self.community_cache.get(book.id),
                news=self.news_cache.get(book.id),
            ),
            "capture": book.capture_snapshot(),
            "risk_calendar": self.risk_snapshot(),
        }

    def _durable_trade_row(
        self,
        trade: dict[str, Any],
    ) -> dict[str, Any]:
        aid = str(trade.get("asset_id") or "")
        book = self.by_id.get(aid)
        return {
            **dict(trade),
            "symbol": trade.get("symbol") or (book.symbol if book else aid.upper()),
            "pair": trade.get("pair") or (book.pair if book else aid.upper()),
            "broker": trade.get("broker") or (book.broker if book else None),
        }

    def merge_blotter_history(
        self,
        durable: list[dict[str, Any]],
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Merge durable PostgreSQL history with current in-memory/file history."""
        combined: dict[str, dict[str, Any]] = {}

        def key_for(row: dict[str, Any]) -> str:
            trade_id = str(row.get("trade_id") or "").strip()
            if trade_id:
                return trade_id
            return "|".join(
                (
                    str(row.get("asset_id") or row.get("pair") or ""),
                    str(row.get("opened_at") or ""),
                    str(row.get("closed_at") or row.get("ts") or ""),
                    str(row.get("entry_price") or ""),
                    str(row.get("exit_price") or row.get("price") or ""),
                )
            )

        for row in durable:
            if isinstance(row, dict):
                combined[key_for(row)] = dict(row)
        for row in self.blotter(max(int(limit), 1000)):
            # Current runtime rows may contain newer annotations; prefer them.
            combined[key_for(row)] = {
                **combined.get(key_for(row), {}),
                **dict(row),
            }

        rows = list(combined.values())
        rows.sort(
            key=lambda row: str(row.get("closed_at") or row.get("ts") or ""),
            reverse=True,
        )
        return rows[: max(1, int(limit))]

    def blotter(self, limit: int = 200) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for trade in self.wallet.closed_trades:
            aid = str(trade.get("asset_id") or "")
            book = self.by_id.get(aid)
            trade_id = str(trade.get("trade_id") or "")
            if trade_id:
                seen.add(trade_id)
            rows.append(self._durable_trade_row(trade))

        # Preserve pre-upgrade paper history. These rows may not have enough
        # information for exact duration, but are never discarded.
        for book in self.books:
            for fill in book.fills:
                if fill.get("event"):
                    continue
                fill_side = str(fill.get("side") or "").lower()
                if fill_side not in {"buy", "sell"}:
                    continue
                if fill.get("pnl") is None:
                    continue
                position_side = str(
                    fill.get("position_side")
                    or ("short" if fill_side == "buy" else "long")
                ).lower()
                if position_side not in {"long", "short"}:
                    position_side = "long"
                legacy_id = str(
                    fill.get("trade_id")
                    or f"legacy-{book.id}-{fill.get('ts')}"
                )
                if legacy_id in seen:
                    continue
                rows.append(
                    {
                        "trade_id": legacy_id,
                        "asset_id": book.id,
                        "symbol": book.symbol,
                        "pair": book.pair,
                        "broker": book.broker,
                        "side": position_side,
                        "mode": fill.get("entry_mode"),
                        "entry_price": fill.get(
                            "entry_fill_price"
                        ),
                        "exit_price": fill.get("price"),
                        "opened_at": fill.get("opened_at"),
                        "closed_at": fill.get("ts"),
                        "duration_seconds": fill.get(
                            "duration_seconds"
                        ),
                        "quantity": fill.get("qty"),
                        "realized_pnl_usd": fill.get("pnl"),
                        "fees_usd": fill.get(
                            "fees_usd",
                            fill.get("fee"),
                        ),
                        "net_return_pct": fill.get(
                            "net_return_pct"
                        ),
                        "mfe_pct": fill.get("mfe_pct"),
                        "mae_pct": fill.get("mae_pct"),
                        "capture_efficiency_pct": fill.get(
                            "capture_efficiency_pct"
                        ),
                        "exit_reason": fill.get("actor"),
                        "legacy": True,
                    }
                )

        rows.sort(
            key=lambda row: str(
                row.get("closed_at")
                or row.get("ts")
                or ""
            ),
            reverse=True,
        )
        return rows[: max(1, int(limit))]

    def fill_ledger(
        self,
        limit: int = 300,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for book in self.books:
            for fill in book.fills:
                rows.append(
                    {
                        **fill,
                        "asset_id": book.id,
                        "symbol": book.symbol,
                        "pair": book.pair,
                        "broker": book.broker,
                    }
                )
        rows.sort(
            key=lambda row: str(row.get("ts") or ""),
            reverse=True,
        )
        return rows[: max(1, int(limit))]

    async def add_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        asset_id = str(asset.get("id") or "").lower()
        if not asset_id:
            return {"ok": False, "error": "invalid_asset"}
        if asset_id in self.by_id:
            return {
                "ok": True,
                "already_added": True,
                "asset": self.asset_snapshot(asset_id),
            }
        registered = register_asset(asset)
        book = PairBook(registered, self.wallet)
        try:
            bars = await venue.fetch_bars(interval=1, limit=400, pair=book.kraken)
            bars = completed_bars(bars, 60)
            book.seed(bars)
            context = await venue.fetch_bars(interval=60, limit=720, pair=book.kraken)
            context = completed_bars(context, 3600)
            book.seed_context(context)
        except Exception as exc:
            logger.warning("new asset seed failed %s %s", book.pair, exc)
        self.books.append(book)
        self.by_id[book.id] = book
        self.asset_source_registry = merge_source_registry(
            self.asset_source_registry,
            [item.id for item in self.books],
        )
        self.persist()
        return {
            "ok": True,
            "already_added": False,
            "asset": self.asset_snapshot(book.id),
        }

    async def seed(self) -> None:
        for book in self.books:
            source = book.kraken or book.id
            try:
                bars = await venue.fetch_bars(
                    interval=1,
                    limit=400,
                    pair=source,
                )
                bars = completed_bars(bars, 60)
                book.seed(bars)

                context = await venue.fetch_bars(
                    interval=60,
                    limit=720,
                    pair=source,
                )
                context = completed_bars(context, 3600)
                book.seed_context(context)

                daily = await venue.fetch_bars(
                    interval=1440,
                    limit=260,
                    pair=source,
                )
                daily = completed_bars(daily, 86400)
                book.seed_daily(daily)
            except Exception as exc:
                logger.warning("seed failed %s %s", book.pair, exc)
        if not self.strategy_router.clock.last_bucket:
            closed_ts = self._latest_closed_minute_ts()
            if closed_ts is not None:
                self.strategy_router.due(closed_ts)
        seeded_at = time.time()
        self._last_context_refresh = seeded_at
        self._last_daily_refresh = seeded_at

    async def _refresh_context_bars(
        self,
        force: bool = False,
    ) -> None:
        now = time.time()
        hourly_due = (
            force
            or now - self._last_context_refresh >= 1800
        )
        daily_due = (
            force
            or now - self._last_daily_refresh >= 14400
        )
        if not hourly_due and not daily_due:
            return

        if hourly_due:
            self._last_context_refresh = now
        if daily_due:
            self._last_daily_refresh = now

        for book in self.books:
            source = book.kraken or book.id
            try:
                if hourly_due:
                    context = await venue.fetch_bars(
                        interval=60,
                        limit=720,
                        pair=source,
                    )
                    context = completed_bars(context, 3600)
                    if context:
                        book.seed_context(context)

                if daily_due:
                    daily = await venue.fetch_bars(
                        interval=1440,
                        limit=260,
                        pair=source,
                    )
                    daily = completed_bars(daily, 86400)
                    if daily:
                        book.seed_daily(daily)
            except Exception as exc:
                logger.warning(
                    "context refresh failed %s %s",
                    book.pair,
                    exc,
                )

    async def _refresh_one_news(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_news_refresh < 45:
            return
        self._last_news_refresh = now
        if not self.books:
            return
        book = self.books[self._news_cursor % len(self.books)]
        self._news_cursor = (self._news_cursor + 1) % max(len(self.books), 1)
        try:
            result = await fetch_asset_news(
                book.id,
                name=book.name,
                symbol=book.symbol,
            )
            result["fetched_at"] = now
            self.news_cache[book.id] = result
        except Exception as exc:
            self.news_cache[book.id] = {
                "asset_id": book.id,
                "status": "degraded",
                "shadow_only": True,
                "trade_influence_enabled": False,
                "note": f"News refresh failed: {type(exc).__name__}",
                "fetched_at": now,
            }

    async def _refresh_one_community(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_community_refresh < 30:
            return
        self._last_community_refresh = now
        if not self.books:
            return
        book = self.books[self._community_cursor % len(self.books)]
        self._community_cursor = (self._community_cursor + 1) % max(len(self.books), 1)
        try:
            result = await fetch_reddit(book.id)
            result["fetched_at"] = now
            self.community_cache[book.id] = result
        except Exception as exc:
            self.community_cache[book.id] = {
                "asset_id": book.id,
                "status": "degraded",
                "shadow_only": True,
                "trade_influence_enabled": False,
                "note": f"Community refresh failed: {type(exc).__name__}",
                "fetched_at": now,
            }

    async def _refresh_risk_calendar(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_risk_refresh < 300:
            return
        self._last_risk_refresh = now
        try:
            events = await fetch_calendar()
            self.risk_calendar_connected = True
            try:
                events, official = await verify_macro_events(events)
                self.official_macro_sources = official
            except Exception as exc:
                self.official_macro_sources = {
                    "bls": {
                        "connected": False,
                        "status": "degraded",
                        "note": f"Official verification failed: {type(exc).__name__}",
                    },
                    "federal_reserve": {
                        "connected": False,
                        "status": "planned",
                    },
                    "bea": {
                        "connected": False,
                        "status": "planned",
                    },
                }
                logger.warning("official macro verification failed %s", exc)
            self.risk_events = events
        except Exception as exc:
            self.risk_calendar_connected = False
            logger.warning("risk calendar refresh failed %s", exc)

    def risk_snapshot(self) -> dict[str, Any]:
        state = active_risk(self.risk_events)
        return {
            **state,
            "calendar_connected": self.risk_calendar_connected,
            "official_sources": self.official_macro_sources,
            "events": self.risk_events,
            "crypto_calendar": {
                "provider": "CoinMarketCal",
                "configured": self.crypto_calendar_configured,
                "connected": self.crypto_calendar_connected,
                "status": self.crypto_calendar_status,
                "events": self.crypto_events,
            },
            "policy": {
                "mode": "observe_only",
                "automatic_entry_block": False,
                "crypto_event_enforcement": False,
                "note": "Risk windows are visible now; strategy enforcement remains disabled until validated.",
            },
        }

    async def _refresh_crypto_calendar(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_crypto_refresh < 900:
            return
        self._last_crypto_refresh = now
        feed = await fetch_crypto_calendar([book.symbol for book in self.books])
        self.crypto_calendar_configured = bool(feed.get("configured"))
        self.crypto_calendar_connected = bool(feed.get("connected"))
        self.crypto_calendar_status = str(feed.get("status") or "unavailable")
        self.crypto_events = [
            row for row in (feed.get("events") or [])
            if isinstance(row, dict)
        ]

    @staticmethod
    def _summary_without_rows(
        payload: dict[str, Any] | None,
        row_key: str,
    ) -> dict[str, Any]:
        summary = dict(payload or {})
        summary.pop(row_key, None)
        return summary

    def _intelligence_observations(
        self,
        book: PairBook,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        news = self.news_cache.get(book.id) or {}
        for article in news.get("articles") or []:
            if not isinstance(article, dict):
                continue
            rows.append(
                {
                    "source_type": "news",
                    "source_name": article.get("domain") or "GDELT",
                    "external_id": article.get("url") or article.get("title"),
                    "published_at": article.get("seen_at"),
                    "payload": article,
                }
            )
        community = self.community_cache.get(book.id) or {}
        for post in community.get("posts") or []:
            if not isinstance(post, dict):
                continue
            rows.append(
                {
                    "source_type": "community",
                    "source_name": community.get("source") or "community",
                    "external_id": post.get("permalink") or post.get("title"),
                    "published_at": post.get("created_at"),
                    "payload": post,
                }
            )
        for event in self.risk_events:
            if not isinstance(event, dict):
                continue
            rows.append(
                {
                    "source_type": "macro_event",
                    "source_name": event.get("source") or "macro_calendar",
                    "external_id": "|".join(
                        (
                            str(event.get("scheduled_at") or ""),
                            str(event.get("title") or ""),
                        )
                    ),
                    "published_at": None,
                    "payload": event,
                }
            )
        symbol = str(book.symbol).lower()
        for event in self.crypto_events:
            if not isinstance(event, dict):
                continue
            event_symbols = {
                str(coin.get("symbol") or "").lower()
                for coin in (event.get("coins") or [])
                if isinstance(coin, dict)
            }
            if symbol not in event_symbols:
                continue
            rows.append(
                {
                    "source_type": "crypto_event",
                    "source_name": event.get("provider") or "CoinMarketCal",
                    "external_id": event.get("provider_event_id") or event.get("title"),
                    "published_at": event.get("provider_verified_at"),
                    "payload": event,
                }
            )
        return rows

    async def _persist_intelligence(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_intelligence_persist < 300:
            return
        self._last_intelligence_persist = now
        if not db_store.initialized:
            return
        batch: list[dict[str, Any]] = []
        for book in self.books:
            context = asset_context(
                book,
                self.books,
                events=self.risk_events,
                calendar_connected=self.risk_calendar_connected,
                community=self.community_cache.get(book.id),
                news=self.news_cache.get(book.id),
            )
            context = dict(context)
            context["news"] = self._summary_without_rows(
                context.get("news"),
                "articles",
            )
            context["community"] = self._summary_without_rows(
                context.get("community"),
                "posts",
            )
            batch.append(
                {
                    "asset_id": book.id,
                    "pair": book.pair,
                    "price_usd": book.mark,
                    "context": context,
                    "capture": book.capture_snapshot(),
                    "observations": self._intelligence_observations(book),
                }
            )
        ok = await db_store.save_intelligence_snapshots(batch)
        if not ok and db_store.last_error:
            logger.warning(
                "intelligence persistence failed %s",
                db_store.last_error,
            )

    async def _quotes(self) -> None:
        try:
            items = await venue.fetch_markets()
        except Exception as exc:
            self._last_market_error = f"{type(exc).__name__}: {exc}"
            logger.warning("markets failed %s", exc)
            return
        self._last_market_success = time.time()
        self._last_market_error = None
        ts = int(time.time())
        for item in items:
            book = self.by_id.get(str(item.get("id")))
            if not book:
                continue
            book.apply_quote(item)
            book.push_px(ts)

    def _allocate(self) -> list[dict[str, Any]]:
        if not self.armed:
            return []

        equity = max(self.wallet.equity(self.marks()), 1.0)
        risk_budget_usd = equity * TRADE_RISK_FRACTION
        capital_cap_usd = min(
            equity * self.risk_slice,
            max(self.wallet.usd * 0.95, 0.0),
        )
        btc_bias, btc_long = self._btc_gate()

        open_books = [
            book
            for book in self.books
            if book.qty() > 0
        ]
        group_counts: dict[str, int] = {}
        for book in open_books:
            group = str(
                playbook_profile(book.id)["cluster"]
            )
            group_counts[group] = (
                group_counts.get(group, 0) + 1
            )

        due_routes = ()
        if not self.execution_test_mode:
            closed_ts = self._latest_closed_minute_ts()
            if closed_ts is None:
                return []
            due_routes = self.strategy_router.due(closed_ts)
            if not due_routes:
                return []

        candidates: list[
            tuple[int, PairBook, dict[str, Any]]
        ] = []
        for book in self.books:
            # Keep one-position-per-book intact even during the experiment.
            # This is an execution invariant, not a strategy threshold.
            if book.qty() > 0:
                continue

            if self.execution_test_mode:
                try:
                    baseline = book.snapshot_strategy(
                        btc_bias_on=btc_bias,
                        btc_in_position=btc_long,
                    )
                except Exception as exc:
                    baseline = {
                        "reason": f"strategy_error:{type(exc).__name__}",
                        "execution_status": "strategy_error",
                        "quality_score": 0,
                    }
                snap = {
                    **baseline,
                    "signal": "buy",
                    "executable_signal": "buy",
                    "mode": "execution_test",
                    "reason": "execution_test_mode",
                    "execution_status": "execution_test_forced",
                    "signal_key": (
                        f"execution-test:{book.id}:{int(time.time()) // 60}"
                    ),
                    "risk_stop_pct": 10.0,
                    "entry_clock": "desk_tick",
                    "bias_clock": "bypassed",
                    "execution_test": True,
                    "would_have_blocked_by": baseline.get("reason"),
                    "normal_execution_status": baseline.get("execution_status"),
                    "normal_signal": baseline.get("executable_signal"),
                    "normal_quality_score": baseline.get("quality_score"),
                }
                candidates.append(
                    (
                        int(baseline.get("quality_score") or 0),
                        book,
                        snap,
                    )
                )
                continue

            route_candidates: list[
                tuple[int, dict[str, Any]]
            ] = []
            for route in due_routes:
                for horizon in supported_horizons(book.id):
                    if (
                        clock_horizon(book.id, horizon)
                        != route.horizon.value
                    ):
                        continue
                    mode = execution_mode(book.id, horizon)
                    try:
                        snap = book.snapshot_strategy(
                            btc_bias_on=btc_bias,
                            btc_in_position=btc_long,
                            requested_mode=mode,
                        )
                    except Exception:
                        logger.exception(
                            "strategy route failed asset=%s horizon=%s",
                            book.id,
                            horizon,
                        )
                        continue
                    snap = {
                        **snap,
                        "routing_horizon": horizon,
                        "clock_horizon": route.horizon.value,
                        "strategy_id": route.strategy_id,
                        "strategy_version": route.strategy_version,
                    }
                    if snap.get("executable_signal") not in {
                        "buy",
                        "short",
                    }:
                        continue
                    route_candidates.append(
                        (
                            int(snap.get("quality_score") or 0),
                            snap,
                        )
                    )

            if not route_candidates:
                continue
            route_candidates.sort(
                key=lambda row: row[0],
                reverse=True,
            )
            quality, snap = route_candidates[0]
            candidates.append((quality, book, snap))

        out: list[dict[str, Any]] = []
        candidates.sort(
            key=lambda row: row[0],
            reverse=True,
        )
        active_count = len(open_books)
        active_limit = (
            len(self.books)
            if self.execution_test_mode
            else MAX_ACTIVE_POSITIONS
        )

        for _, book, snap in candidates:
            if active_count >= active_limit:
                break

            profile = playbook_profile(book.id)
            group = str(profile["cluster"])
            if (
                not self.execution_test_mode
                and group_counts.get(group, 0)
                >= int(profile["cluster_cap"])
            ):
                continue
            if float(book.mark or 0.0) <= 0:
                continue
            if (
                not self.execution_test_mode
                and (risk_budget_usd <= 0 or capital_cap_usd <= 0)
            ):
                continue

            result = book.enter(
                risk_budget_usd,
                strategy_snapshot=snap,
                max_capital_usd=(
                    None
                    if self.execution_test_mode
                    else capital_cap_usd
                ),
                execution_test=self.execution_test_mode,
            )
            result["playbook"] = snap.get("mode")
            result["quality_score"] = snap.get(
                "quality_score"
            )
            result["risk_budget_usd"] = round(
                risk_budget_usd,
                4,
            )
            result["capital_cap_usd"] = round(
                capital_cap_usd,
                4,
            )
            out.append(result)

            if result.get("ok"):
                active_count += 1
                group_counts[group] = (
                    group_counts.get(group, 0) + 1
                )
                self._record_event(
                    "entry_filled",
                    book,
                    {
                        "trade_id": result.get("trade_id"),
                        "side": result.get("position_side"),
                        "mode": result.get("entry_mode"),
                        "price": result.get("price"),
                        "quantity": result.get("qty"),
                        "stop_price": book.stop or None,
                        "risk_budget_usd": result.get(
                            "risk_budget_usd"
                        ),
                        "quality_score": result.get(
                            "quality_score"
                        ),
                        "execution_test": self.execution_test_mode,
                        "routing_horizon": snap.get(
                            "routing_horizon"
                        ),
                        "clock_horizon": snap.get(
                            "clock_horizon"
                        ),
                        "strategy_id": snap.get("strategy_id"),
                        "strategy_version": snap.get(
                            "strategy_version"
                        ),
                        "would_have_blocked_by": snap.get(
                            "would_have_blocked_by"
                        ),
                    },
                )
                self.persist()

                if book.kraken and not self.execution_test_mode:
                    asyncio.create_task(
                        live.place_order(
                            pair=book.kraken,
                            side=str(
                                result.get("execution_side")
                                or "buy"
                            ),
                            volume=float(
                                result.get("qty") or 0
                            ),
                        )
                    )
        if (
            due_routes
            and not self.execution_test_mode
            and not any(row.get("ok") for row in out)
        ):
            self.persist()
        return out

    async def _retire_execution_test_positions(
        self,
    ) -> list[dict[str, Any]]:
        """Close legacy LOAD-002 experiment positions before normal routing."""
        if self.execution_test_mode:
            return []

        retired: list[dict[str, Any]] = []
        for book in self.books:
            position = self.wallet.position(book.id)
            if not position:
                continue
            metadata = position.get("metadata") or {}
            if not (
                bool(position.get("execution_test_funded"))
                or bool(metadata.get("execution_test"))
            ):
                continue

            mark = float(book.mark or 0.0)
            if mark <= 0:
                continue

            row = self.wallet.close_position(
                book.id,
                price=mark,
                exit_reason="execution_test_retired",
                reference_price=mark,
            )
            if not row.get("ok"):
                continue

            row["pair"] = book.pair
            row["symbol"] = book.symbol
            row["broker"] = book.broker
            row["actor"] = "system-execution-test-retirement"
            row["event"] = "exit"
            row["position_side"] = position.get("side")
            row["entry_mode"] = position.get("mode")

            book.entry_at = None
            book.entry_mode = None
            book.stop = 0.0
            book.highest = 0.0
            book.lowest = 0.0

            self._record_event(
                "position_closed",
                book,
                {
                    "trade_id": row.get("trade_id"),
                    "side": row.get("position_side"),
                    "mode": row.get("entry_mode"),
                    "price": row.get("price"),
                    "realized_pnl_usd": row.get("pnl"),
                    "duration_seconds": row.get("duration_seconds"),
                    "exit_reason": "execution_test_retired",
                    "execution_test": True,
                },
            )
            retired.append(row)

            if db_store.initialized:
                durable = self._durable_trade_row(row)
                saved = await db_store.save_desk_trades([durable])
                if not saved and db_store.last_error:
                    logger.warning(
                        "execution-test retirement durable write failed %s",
                        db_store.last_error,
                    )

        if retired:
            self.persist()
        return retired

    async def tick(self) -> None:
        await self._refresh_risk_calendar()
        await self._refresh_crypto_calendar()
        await self._refresh_one_community()
        await self._refresh_one_news()
        await self._quotes()
        await self._refresh_context_bars()
        await self._persist_intelligence()

        retired = await self._retire_execution_test_positions()
        exits = list(retired)
        ordered_books = sorted(
            self.books,
            key=lambda item: 0 if item.id == "btc" else 1,
        )
        for book in ordered_books:
            # Re-read the BTC gate before every managed book. If BTC exits
            # earlier in this tick, ETH sees the closed rider gate immediately.
            btc_bias, btc_long = self._btc_gate()
            before_stop = float(book.stop or 0.0)
            before_trade = self.wallet.position(book.id)
            row = book.manage(
                btc_bias_on=btc_bias,
                btc_in_position=btc_long,
            )
            after_stop = float(book.stop or 0.0)
            if (
                row is None
                and before_trade
                and after_stop > 0
                and abs(after_stop - before_stop) > 1e-10
            ):
                self._record_event(
                    "stop_moved",
                    book,
                    {
                        "trade_id": before_trade.get(
                            "trade_id"
                        ),
                        "side": before_trade.get("side"),
                        "from_price": (
                            before_stop
                            if before_stop > 0
                            else None
                        ),
                        "to_price": after_stop,
                    },
                )
                self.persist()
            if row:
                exits.append(row)
                self._record_event(
                    "position_closed",
                    book,
                    {
                        "trade_id": row.get("trade_id"),
                        "side": row.get("position_side"),
                        "mode": row.get("entry_mode"),
                        "price": row.get("price"),
                        "realized_pnl_usd": row.get("pnl"),
                        "duration_seconds": row.get(
                            "duration_seconds"
                        ),
                        "exit_reason": row.get("exit_reason"),
                    },
                )
                durable_row = self._durable_trade_row(row)
                if db_store.initialized:
                    saved = await db_store.save_desk_trades([durable_row])
                    if not saved and db_store.last_error:
                        logger.warning(
                            "closed trade durable write failed %s",
                            db_store.last_error,
                        )
                self.persist()
                if book.kraken and not self.execution_test_mode:
                    await live.place_order(
                        pair=book.kraken,
                        side=str(
                            row.get("execution_side")
                            or "sell"
                        ),
                        volume=float(
                            row.get("qty") or 0
                        ),
                    )
        entries = [] if retired else self._allocate()
        if entries or exits:
            logger.info(
                "desk entries=%s exits=%s usd=%.2f",
                len(entries),
                len(exits),
                self.wallet.usd,
            )

    def start(self) -> None:
        if self._task and not self._task.done():
            return

        async def loop():
            await self.seed()
            await self._refresh_risk_calendar(force=True)
            await self._refresh_crypto_calendar(force=True)
            await self._refresh_one_community(force=True)
            await self._refresh_one_news(force=True)
            await self._quotes()
            await self._persist_intelligence(force=True)
            while True:
                try:
                    await self.tick()
                except Exception:
                    logger.exception("desk tick")
                await asyncio.sleep(self.poll_seconds)

        self._task = asyncio.create_task(loop())

    def arm(self) -> dict[str, Any]:
        self.armed = True
        self.start()
        self.persist()
        data = self.snapshot()
        data["engine"] = self.engine_status()
        return data

    def disarm(self) -> dict[str, Any]:
        self.armed = False
        self.persist()
        data = self.snapshot()
        data["engine"] = self.engine_status()
        return data


# LOAD-002 execution rail experiment is complete. Production now runs the
# normal paper strategy router; live orders remain hard-blocked in app.live.
desk = MultiDesk(execution_test_mode=False)
