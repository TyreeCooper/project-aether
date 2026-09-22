"""Start the one-account desk after the paper engine is installed."""
from __future__ import annotations

import asyncio
import os


def attach(engine) -> None:
    from app.desk import desk
    from app.fees import fee_quote, theme
    from app.intel import build_intel

    original = engine.snapshot
    original_asset = desk.asset_snapshot
    raw_buy = desk.wallet.buy
    raw_sell = desk.wallet.sell

    def buy(asset, qty, price, fee_rate=None):
        quote = fee_quote(asset, qty=qty, price=price, side="buy")
        out = raw_buy(asset, qty, price, fee_rate=quote["rate"])
        if out.get("ok"):
            out["fee_model"] = quote
            out["fee"] = quote["fee_usd"] if quote.get("model") != "percent_taker" else out.get("fee")
        return out

    def sell(asset, qty, price, fee_rate=None):
        quote = fee_quote(asset, qty=qty, price=price, side="sell")
        out = raw_sell(asset, qty, price, fee_rate=quote["rate"])
        if out.get("ok"):
            out["fee_model"] = quote
        return out

    desk.wallet.buy = buy
    desk.wallet.sell = sell

    def snapshot():
        data = original()
        data["desk"] = desk.snapshot()
        return data

    def asset_snapshot(asset_id: str):
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
                    {
                        "key": "broker",
                        "label": "Broker",
                        "means": "Who would execute this book live",
                        "value": skin["label"],
                        "unit": "",
                    },
                    {
                        "key": "model",
                        "label": "Fee model",
                        "means": "How the ticket is calculated",
                        "value": quote.get("model"),
                        "unit": "",
                    },
                    {
                        "key": "rate",
                        "label": "Effective rate",
                        "means": "Fee as a fraction of notional on a 1-unit example",
                        "value": quote.get("rate"),
                        "unit": "",
                    },
                    {
                        "key": "source",
                        "label": "Source",
                        "means": "Published schedule this number came from",
                        "value": quote.get("source"),
                        "unit": "",
                    },
                ],
            },
        )
        data["intel"] = intel
        data["broker"] = skin
        data["fee"] = quote
        book = desk.by_id.get(str(asset_id).lower())
        if book is not None:
            book.last_intel = intel
            book.fee_quote = quote
        return data

    engine.snapshot = snapshot
    desk.asset_snapshot = asset_snapshot
    desk.start()
    engine._log("INFO", "Per-broker fees bound. Asset pages inherit broker color.")

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
