"""Start the one-account desk after the paper engine is installed."""
from __future__ import annotations

import asyncio
import os


def attach(engine) -> None:
    from app.desk import desk
    from app.intel import build_intel

    original = engine.snapshot
    original_asset = desk.asset_snapshot

    def snapshot():
        data = original()
        data["desk"] = desk.snapshot()
        return data

    def asset_snapshot(asset_id: str):
        data = original_asset(asset_id)
        if not data:
            return data
        intel = build_intel(
            view=data.get("asset") or {},
            strategy=data.get("strategy") or {},
            analytics=data.get("analytics") or {},
            capture=data.get("capture") or {},
            window=data.get("window") or {},
        )
        data["intel"] = intel
        book = desk.by_id.get(str(asset_id).lower())
        if book is not None:
            book.last_intel = intel
        return data

    engine.snapshot = snapshot
    desk.asset_snapshot = asset_snapshot
    desk.start()
    engine._log("INFO", "Multi-desk on. Shared intel pack on every asset page.")

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
