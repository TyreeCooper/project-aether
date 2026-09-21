"""Kraken-style desk: one USD stack, ten pair books, one rule."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from app import live, venue
from app.clock import is_new_five_minute
from app.desk_persist import load_desk, save_desk
from app.universe import ASSETS
from app.wallet import STARTING_USD, SpotWallet
from app.pair_book import PairBook

logger = logging.getLogger("aether.desk")
RISK_SLICE = 0.08
POLL = 20


class MultiDesk:
    def __init__(self) -> None:
        self.wallet = SpotWallet(STARTING_USD)
        self.books = [PairBook(asset, self.wallet) for asset in ASSETS]
        self.by_id = {b.id: b for b in self.books}
        self._task: asyncio.Task | None = None
        self.armed = os.getenv("AETHER_AUTO_RUN", "1").strip() not in {"0", "false", "FALSE"}
        self.live_blocked = True
        self._restore()

    def marks(self) -> dict[str, float]:
        return {b.id: float(b.mark or 0.0) for b in self.books}

    def persist(self) -> None:
        books = {}
        for book in self.books:
            books[book.id] = {
                "stop": book.stop,
                "highest": book.highest,
                "entry_at": book.entry_at,
                "last_reason": book.last_reason,
            }
        save_desk(
            {
                "wallet": self.wallet.payload(),
                "books": books,
                "armed": self.armed,
                "saved_at": time.time(),
            }
        )

    def _restore(self) -> None:
        data = load_desk()
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
                book.last_reason = str(row.get("last_reason") or book.last_reason)
        if "armed" in data:
            self.armed = bool(data["armed"])
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
            "model": "one_kraken_spot_account",
            "persists": True,
        }

    async def seed(self) -> None:
        for book in self.books:
            try:
                bars = await venue.fetch_bars(interval=1, limit=400, pair=book.kraken)
                if len(bars) > 1:
                    bars = bars[:-1]
                book.seed(bars)
            except Exception as exc:
                logger.warning("seed failed %s %s", book.pair, exc)

    async def _quotes(self) -> None:
        try:
            items = await venue.fetch_markets()
        except Exception as exc:
            logger.warning("markets failed %s", exc)
            return
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
        slice_usd = equity * RISK_SLICE
        out: list[dict[str, Any]] = []
        for book in self.books:
            fresh, bucket = is_new_five_minute(list(book.bars), book.last_5m)
            if book.last_5m is None and bucket is not None:
                book.last_5m = bucket
                continue
            if bucket is not None:
                book.last_5m = bucket
            if not fresh:
                continue
            if not book.wants_entry():
                continue
            result = book.enter(min(slice_usd, max(self.wallet.usd * 0.95, 0.0)))
            out.append(result)
            if result.get("ok"):
                self.persist()
                asyncio.create_task(
                    live.place_order(
                        pair=book.kraken,
                        side="buy",
                        volume=float(result.get("qty") or 0),
                    )
                )
        return out

    async def tick(self) -> None:
        await self._quotes()
        exits = []
        for book in self.books:
            row = book.manage()
            if row:
                exits.append(row)
                self.persist()
                await live.place_order(
                    pair=book.kraken,
                    side="sell",
                    volume=float(row.get("qty") or 0),
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
        if self._task:
            return

        async def loop():
            await self.seed()
            while True:
                try:
                    await self.tick()
                except Exception:
                    logger.exception("desk tick")
                await asyncio.sleep(POLL)

        self._task = asyncio.create_task(loop())

    def arm(self) -> dict[str, Any]:
        self.armed = True
        self.persist()
        return self.snapshot()

    def disarm(self) -> dict[str, Any]:
        self.armed = False
        self.persist()
        return self.snapshot()


desk = MultiDesk()
