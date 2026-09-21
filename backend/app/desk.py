"""Kraken-style desk: one USD stack, ten pair books, one rule."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app import live, venue
from app.clock import is_new_five_minute
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
        self.armed = True
        self.live_blocked = True

    def marks(self) -> dict[str, float]:
        return {b.id: float(b.mark or 0.0) for b in self.books}

    def snapshot(self) -> dict[str, Any]:
        wallet = self.wallet.snapshot(self.marks())
        return {
            "wallet": wallet,
            "books": [b.view() for b in self.books],
            "armed": self.armed,
            "live": live.status(),
            "live_blocked": True,
            "model": "one_kraken_spot_account",
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
        return self.snapshot()

    def disarm(self) -> dict[str, Any]:
        self.armed = False
        return self.snapshot()


desk = MultiDesk()
