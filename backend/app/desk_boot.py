"""Start the one-account desk after the paper engine is installed."""
from __future__ import annotations

import asyncio
import os


def attach(engine) -> None:
    from app import venue
    from app.desk import desk
    from app.fees import fee_quote, theme
    from app.intel import build_intel
    from app.kraken_ws import stream as kraken_stream
    from app.pipes import asset_id_from_pair, enrich_markets, fetch_yahoo_bars
    from app.sessions import desk_board, for_asset
    from app.universe import ALLOWED_IDS

    orig_markets = venue.fetch_markets
    orig_bars = venue.fetch_bars

    async def fetch_markets():
        try:
            items = await orig_markets()
        except Exception:
            items = []
        items = await enrich_markets(items)
        return [row for row in items if str(row.get("id") or "").lower() in ALLOWED_IDS]

    async def fetch_bars(interval=1, limit=720, pair="XBTUSD"):
        bars = []
        if pair:
            try:
                bars = await orig_bars(interval=interval, limit=limit, pair=pair)
            except Exception:
                bars = []
        if bars:
            return bars
        aid = asset_id_from_pair(str(pair or ""))
        if not aid or aid not in ALLOWED_IDS:
            return []
        y_int = {
            1: "1m",
            5: "5m",
            60: "60m",
            1440: "1d",
        }.get(int(interval or 1), "1m")
        return await fetch_yahoo_bars(aid, interval=y_int, limit=limit)

    venue.fetch_markets = fetch_markets
    venue.fetch_bars = fetch_bars

    original = engine.snapshot
    original_asset = desk.asset_snapshot
    original_floor = desk.floor_snapshot
    raw_buy = desk.wallet.buy
    raw_sell = desk.wallet.sell

    def buy(asset, qty, price, fee_rate=None):
        if str(asset).lower() not in ALLOWED_IDS:
            return {"ok": False, "error": "asset not on the 12-book desk"}
        quote = fee_quote(asset, qty=qty, price=price, side="buy")
        out = raw_buy(asset, qty, price, fee_rate=quote["rate"])
        if out.get("ok"):
            out["fee_model"] = quote
            out["fee"] = quote["fee_usd"] if quote.get("model") != "percent_taker" else out.get("fee")
        return out

    def sell(asset, qty, price, fee_rate=None):
        if str(asset).lower() not in ALLOWED_IDS:
            return {"ok": False, "error": "asset not on the 12-book desk"}
        quote = fee_quote(asset, qty=qty, price=price, side="sell")
        out = raw_sell(asset, qty, price, fee_rate=quote["rate"])
        if out.get("ok"):
            out["fee_model"] = quote
        return out

    desk.wallet.buy = buy
    desk.wallet.sell = sell

    extra = [k for k in list(getattr(desk.wallet, "balances", {}) or {}) if k not in ALLOWED_IDS]
    for key in extra:
        desk.wallet.balances.pop(key, None)
    desk.books[:] = [b for b in desk.books if b.id in ALLOWED_IDS]
    desk.by_id = {b.id: b for b in desk.books}
    if extra:
        desk.wallet.save()
        engine._log("INFO", "Dropped leftover alt balances: " + ",".join(extra))

    async def frozen_add(_asset):
        return {"ok": False, "error": "universe frozen to the 12 official books"}

    desk.add_asset = frozen_add

    def snapshot():
        data = original()
        data["desk"] = desk.snapshot()
        data["sessions"] = desk_board()
        return data

    def floor_snapshot():
        data = original_floor()
        data["sessions"] = desk_board()
        return data

    def asset_snapshot(asset_id: str):
        if str(asset_id).lower() not in ALLOWED_IDS:
            return None
        data = original_asset(asset_id)
        if not data:
            return data
        view = data.get("asset") or {}
        intel = build_intel(
            view=view,
            strategy=data.get("strategy") or {},
            analytics=data.get("analytics") or {},
            capture=data.get("capture") or {},
            window=data.get("window") or {},
        )
        quote = fee_quote(asset_id, qty=1.0, price=float(view.get("mark") or 1), side="buy")
        skin = theme(asset_id)
        clock = for_asset(asset_id)
        intel["cards"].insert(
            1,
            {
                "id": "friction",
                "title": "Venue cost",
                "slang": "Taker / ticket",
                "plain": "What this broker charges on a paper fill. Same number the wallet subtracts.",
                "tone": "tape",
                "headline": quote.get("fee_usd"),
                "fields": [
                    {"key": "broker", "label": "Broker", "means": "Who would execute this book live", "value": skin["label"], "unit": ""},
                    {"key": "model", "label": "Fee model", "means": "How the ticket is calculated", "value": quote.get("model"), "unit": ""},
                    {"key": "rate", "label": "Effective rate", "means": "Fee as a fraction of notional on a 1-unit example", "value": quote.get("rate"), "unit": ""},
                    {"key": "source", "label": "Source", "means": "Published schedule this number came from", "value": quote.get("source"), "unit": ""},
                ],
            },
        )
        live = ", ".join(clock["active"]) or "none"
        intel["cards"].insert(
            2,
            {
                "id": "session",
                "title": "Session / clocks",
                "slang": "Where the sun is",
                "plain": clock["sessions"][0]["plain"] if clock["always_open"] else "Cash-session windows in Eastern time. Same object the bot reads.",
                "tone": "good" if clock["active"] else "flat",
                "headline": "24/7" if clock["always_open"] else live,
                "fields": [
                    {"key": "clock", "label": "Desk clock", "means": "America/New_York right now", "value": clock["clock"], "unit": ""},
                    {"key": "kind", "label": "Market type", "means": "Which session calendar this book uses", "value": clock["kind"], "unit": ""},
                    {"key": "active", "label": "Active now", "means": "Sessions that are open at this minute", "value": live, "unit": ""},
                    *[
                        {
                            "key": s["id"],
                            "label": s["name"] + (" · ACTIVE" if s["active"] else ""),
                            "means": s["plain"],
                            "value": s["window"],
                            "unit": "",
                        }
                        for s in clock["sessions"]
                    ],
                    *[
                        {
                            "key": t["id"],
                            "label": t["name"] + " · " + t["role"],
                            "means": t["plain"],
                            "value": t["role"],
                            "unit": "",
                        }
                        for t in clock["timeframes"]
                    ],
                ],
            },
        )
        intel["sessions"] = clock
        data["intel"] = intel
        data["broker"] = skin
        data["fee"] = quote
        data["sessions"] = clock
        book = desk.by_id.get(str(asset_id).lower())
        if book is not None:
            book.last_intel = intel
            book.last_sessions = clock
            book.fee_quote = quote
        return data

    engine.snapshot = snapshot
    desk.asset_snapshot = asset_snapshot
    desk.floor_snapshot = floor_snapshot

    def on_ws_quote(quote):
        book = desk.by_id.get(quote["id"])
        if book is None:
            return
        book.apply_quote(
            {
                "last": quote["last"],
                "bid": quote["bid"],
                "ask": quote["ask"],
                "source": "kraken-ws",
            }
        )
        book.push_px(int(quote["ts"]))

    async def seed_yahoo():
        for book in desk.books:
            if book.bars or book.id in {"btc", "eth"}:
                continue
            try:
                bars = await fetch_yahoo_bars(book.id, interval="1m", limit=240)
                if bars:
                    book.seed(bars)
                    engine._log("INFO", f"Yahoo pipe seeded {book.pair} bars={len(bars)}")
            except Exception as exc:
                engine._log("WARN", f"Yahoo seed skipped {book.pair}: {exc}")

    desk.start()
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(seed_yahoo())
        loop.create_task(kraken_stream(on_ws_quote, engine._log))
    except RuntimeError:
        pass
    engine._log("INFO", "Desk frozen to 12 books. Session clock shared with the bot.")

    auto = os.getenv("AETHER_AUTO_RUN", "1").strip() not in {"0", "false", "FALSE"}
    if auto and getattr(engine, "start_bot", None):

        async def _arm():
            try:
                await engine.start_bot()
                engine._log("INFO", "Auto-run: paper engine armed after restart.")
            except Exception as exc:
                engine._log("WARN", f"Auto-run skipped: {exc}")

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_arm())
        except RuntimeError:
            pass
