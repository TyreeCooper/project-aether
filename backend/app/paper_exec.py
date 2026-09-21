"""Conservative paper execution and market-quality guards."""
from __future__ import annotations

import time

from app.clock import allow_after_losses, close_in_upper_third, is_new_five_minute

SLIPPAGE_BPS = 5.0
MAX_SPREAD_BPS = 10.0
MAX_BASIS_USD = 80.0
STALE_MS = 8_000
REVIEW_EVERY_TICKS = 60


def slipped_price(
    side: str,
    bid: float | None,
    ask: float | None,
    mark: float | None,
) -> float | None:
    raw = ask if side == "buy" else bid
    if raw is None:
        raw = mark
    if raw is None:
        return None
    slip = raw * SLIPPAGE_BPS / 10_000.0
    return raw + slip if side == "buy" else raw - slip


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
    import app.engine as engine_mod

    engine_mod.POLL_SECONDS = 5
    engine_mod.STALE_MS = STALE_MS
    original_tick = engine.tick
    original_eval = engine.evaluate_and_maybe_trade
    ticks = {"n": 0}
    engine._last_5m_bucket = getattr(engine, "_last_5m_bucket", None)

    def guard(side: str = "buy", protective: bool = False) -> str | None:
        stale = True
        last = getattr(engine, "_last_tick_mono", None)
        if last is not None:
            stale = int((time.monotonic() - last) * 1000) > STALE_MS
        reason = deny_microstructure(
            side=side,
            bid=engine.bid,
            ask=engine.ask,
            mark=engine.mark,
            source=engine.mark_source,
            stale=stale,
            watch_last=getattr(engine, "watch_last", None),
            protective=protective,
        )
        if reason:
            return reason
        if protective:
            return None
        bars = list(engine.bars_1m)
        if bars and not close_in_upper_third(bars[-1]):
            return "weak_close"
        if not allow_after_losses(bars, int(getattr(engine, "consecutive_losses", 0) or 0)):
            return "loss_budget"
        return None

    def wrapped_eval(new_bar: bool = False) -> None:
        five, bucket = is_new_five_minute(list(engine.bars_1m), engine._last_5m_bucket)
        if five:
            engine._last_5m_bucket = bucket
        if engine.btc > 0:
            original_eval(new_bar=new_bar)
            return
        original_eval(new_bar=bool(five and new_bar))

    async def wrapped_tick():
        await original_tick()
        ticks["n"] += 1
        if ticks["n"] % REVIEW_EVERY_TICKS:
            return
        try:
            from app import learn
            from app.db import db_store

            fills = await db_store.history_fills(500)
            learn.review(list(engine.bars_1m), fills)
        except Exception as exc:
            engine._log("WARN", f"Journal pass skipped: {exc}")

    engine._paper_entry_guard = guard
    engine.evaluate_and_maybe_trade = wrapped_eval
    engine._fill_price = lambda side: slipped_price(side, engine.bid, engine.ask, engine.mark)
    engine.tick = wrapped_tick
    engine._log("INFO", "Harsh paper on. Entries on closed 5m bars. Two-loss sit until 15m high.")
