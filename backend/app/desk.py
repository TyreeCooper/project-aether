"""Kraken-style desk: one USD stack, ten pair books, one rule."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from app import live, venue
from app.asset_sources import merge_source_registry, registry_summary, set_trust_state
from app.clock import is_new_five_minute
from app.community import fetch_reddit
from app.crypto_events import fetch_crypto_calendar
from app.db import db_store
from app.intelligence import asset_context, floor_intelligence
from app.news import fetch_asset_news
from app.official_macro import verify_macro_events
from app.desk_persist import load_desk, save_desk
from app.events import active_risk, fetch_calendar
from app.fees import fee_rate
from app.playbooks import playbook_profile
from app.universe import ASSETS, export_assets, register_asset
from app.wallet import STARTING_USD, SpotWallet
from app.pair_book import PairBook

logger = logging.getLogger("aether.desk")
RISK_SLICE = 0.08
TRADE_RISK_FRACTION = 0.0075
MAX_ACTIVE_POSITIONS = 4
POLL = 20


class MultiDesk:
    def __init__(self) -> None:
        restored = load_desk()
        if isinstance(restored, dict):
            for asset in restored.get("assets") or []:
                if isinstance(asset, dict):
                    try:
                        register_asset(asset)
                    except (KeyError, TypeError, ValueError):
                        continue
        self.wallet = SpotWallet(STARTING_USD)
        self.books = [PairBook(asset, self.wallet) for asset in ASSETS]
        self.by_id = {b.id: b for b in self.books}
        self._task: asyncio.Task | None = None
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
                "entry_at": book.entry_at,
                "entry_mode": book.entry_mode,
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
                book.entry_at = row.get("entry_at")
                book.entry_mode = row.get("entry_mode")
                book.last_reason = str(row.get("last_reason") or book.last_reason)
                fills = row.get("fills") or []
                if isinstance(fills, list):
                    book.fills = [f for f in fills[-200:] if isinstance(f, dict)]
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
        }

    def settings_snapshot(self) -> dict[str, Any]:
        return {
            "allocation_per_entry_pct": round(self.risk_slice * 100, 2),
            "quote_poll_seconds": int(self.poll_seconds),
            "resume_armed_after_restart": True,
            "state_persistence": True,
        }

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
                "cash": round(float(wallet["usd"]), 4),
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

    def blotter(self, limit: int = 200) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for book in self.books:
            for fill in book.fills:
                rows.append(
                    {
                        **fill,
                        "asset_id": book.id,
                        "symbol": book.symbol,
                        "pair": book.pair,
                    }
                )
        rows.sort(key=lambda row: str(row.get("ts") or ""), reverse=True)
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
            if len(bars) > 1:
                bars = bars[:-1]
            book.seed(bars)
            context = await venue.fetch_bars(interval=60, limit=720, pair=book.kraken)
            if len(context) > 1:
                context = context[:-1]
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
                if len(bars) > 1:
                    bars = bars[:-1]
                book.seed(bars)

                context = await venue.fetch_bars(
                    interval=60,
                    limit=720,
                    pair=source,
                )
                if len(context) > 1:
                    context = context[:-1]
                book.seed_context(context)

                daily = await venue.fetch_bars(
                    interval=1440,
                    limit=260,
                    pair=source,
                )
                if len(daily) > 1:
                    daily = daily[:-1]
                book.seed_daily(daily)
            except Exception as exc:
                logger.warning("seed failed %s %s", book.pair, exc)

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
                    if len(context) > 1:
                        context = context[:-1]
                    if context:
                        book.seed_context(context)

                if daily_due:
                    daily = await venue.fetch_bars(
                        interval=1440,
                        limit=260,
                        pair=source,
                    )
                    if len(daily) > 1:
                        daily = daily[:-1]
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
        slice_usd = equity * self.risk_slice
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

        candidates: list[
            tuple[int, PairBook, dict[str, Any]]
        ] = []
        for book in self.books:
            if book.qty() > 0:
                continue

            fresh, bucket = is_new_five_minute(
                list(book.bars),
                book.last_5m,
            )
            if book.last_5m is None and bucket is not None:
                book.last_5m = bucket
                continue
            if bucket is not None:
                book.last_5m = bucket
            if not fresh:
                continue

            snap = book.snapshot_strategy(
                btc_bias_on=btc_bias,
                btc_in_position=btc_long,
            )
            if snap.get("executable_signal") != "buy":
                continue
            candidates.append(
                (
                    int(snap.get("quality_score") or 0),
                    book,
                    snap,
                )
            )

        out: list[dict[str, Any]] = []
        candidates.sort(
            key=lambda row: row[0],
            reverse=True,
        )
        active_count = len(open_books)

        for _, book, snap in candidates:
            if active_count >= MAX_ACTIVE_POSITIONS:
                break

            profile = playbook_profile(book.id)
            group = str(profile["cluster"])
            if (
                group_counts.get(group, 0)
                >= int(profile["cluster_cap"])
            ):
                continue

            mark = float(book.mark or 0.0)
            if mark <= 0:
                continue

            stop_pct = max(
                float(
                    snap.get("risk_stop_pct")
                    or profile["min_stop_pct"]
                ),
                0.01,
            )
            rate = fee_rate(
                book.id,
                qty=1.0,
                price=mark,
                side="buy",
            )
            cost_pct = max(
                float(snap.get("cost_pct") or 0.0),
                rate * 200,
            )
            modeled_loss_fraction = max(
                (stop_pct + cost_pct) / 100.0,
                1e-6,
            )
            risk_notional = (
                equity
                * TRADE_RISK_FRACTION
                / modeled_loss_fraction
            )
            notional = min(
                slice_usd,
                risk_notional,
                max(self.wallet.usd * 0.95, 0.0),
            )
            if notional <= 0:
                continue

            result = book.enter(
                notional,
                strategy_snapshot=snap,
            )
            result["playbook"] = snap.get("mode")
            result["quality_score"] = snap.get(
                "quality_score"
            )
            out.append(result)

            if result.get("ok"):
                active_count += 1
                group_counts[group] = (
                    group_counts.get(group, 0) + 1
                )
                self.persist()

                if book.kraken:
                    asyncio.create_task(
                        live.place_order(
                            pair=book.kraken,
                            side="buy",
                            volume=float(
                                result.get("qty") or 0
                            ),
                        )
                    )
        return out

    async def tick(self) -> None:
        await self._refresh_risk_calendar()
        await self._refresh_crypto_calendar()
        await self._refresh_one_community()
        await self._refresh_one_news()
        await self._quotes()
        await self._refresh_context_bars()
        await self._persist_intelligence()

        btc_bias, btc_long = self._btc_gate()
        exits = []
        for book in self.books:
            row = book.manage(
                btc_bias_on=btc_bias,
                btc_in_position=btc_long,
            )
            if row:
                exits.append(row)
                self.persist()
                if book.kraken:
                    await live.place_order(
                        pair=book.kraken,
                        side="sell",
                        volume=float(
                            row.get("qty") or 0
                        ),
                    )
        entries = self._allocate()
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
            await self._refresh_context_bars(force=True)
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


desk = MultiDesk()
