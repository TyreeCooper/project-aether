"""Harsh paper execution. Worse than mid-price; still not a live broker."""

from __future__ import annotations

import time

SLIPPAGE_BPS = 5.0
MAX_SPREAD_BPS = 10.0
MAX_BASIS_USD = 80.0
STALE_MS = 15_000
REVIEW_EVERY_TICKS = 40


def slipped_price(side: str, bid: float | None, ask: float | None, mark: float | None) -> float | None:
    raw = ask if side == "buy" else bid
    if raw is None:
        raw = mark
    if raw is None:
        return None
    slip = raw * SLIPPAGE_BPS / 10_000.0
    if side == "buy":
        return raw + slip
    return raw - slip


def deny_microstructure(
    *,
    side: str,
    bid: float | None,
    ask: float | None,
    mark: float | None,
    source: str | None,
    stale: bool,
    watch_last: float | None,
    protective: bool = False,
) -> str | None:
    if protective:
        return None
    if stale:
        return "stale_mark"
    if source == "coingecko":
        return "fallback_mark"
    if mark is None:
        return "no_mark"
    if bid is not None and ask is not None and bid > 0:
        mid = (bid + ask) / 2
        if mid > 0:
            spread_bps = (ask - bid) / mid * 10_000.0
            if spread_bps > MAX_SPREAD_BPS:
                return "wide_spread"
    if watch_last is not None and mark is not None:
        if abs(float(watch_last) - float(mark)) > MAX_BASIS_USD:
            return "wide_basis"
    if slipped_price(side, bid, ask, mark) is None:
        return "no_mark"
    return None


def install(engine) -> None:
    """Slip fills, block dirty entries, and keep a quiet journal."""
    import app.engine as engine_mod

    inner_deny = engine_mod.deny_entry
    original_tick = engine.tick
    ticks = {"n": 0}

    def wrapped_deny(**kwargs):
        reason = inner_deny(**kwargs)
        if reason:
            return reason
        stale = True
        last = getattr(engine, "_last_tick_mono", None)
        if last is not None:
            stale = int((time.monotonic() - last) * 1000) > STALE_MS
        return deny_microstructure(
            side="buy",
            bid=engine.bid,
            ask=engine.ask,
            mark=engine.mark,
            source=engine.mark_source,
            stale=stale,
            watch_last=getattr(engine, "watch_last", None),
        )

    async def wrapped_tick():
        await original_tick()
        ticks["n"] += 1
        if ticks["n"] % REVIEW_EVERY_TICKS:
            return
        try:
            from app import learn
            from app.db import db_store

            fills = await db_store.history_fills(300)
            learn.review(list(engine.closes), fills)
            engine._log("INFO", "Journal wrote a quiet pass.")
        except Exception as exc:
            engine._log("WARN", f"Journal pass skipped: {exc}")

    engine_mod.deny_entry = wrapped_deny
    engine._fill_price = lambda side: slipped_price(side, engine.bid, engine.ask, engine.mark)
    engine.tick = wrapped_tick
    engine._log("INFO", "Harsh paper on. Journal reviews in the background.")
