"""Start the one-account desk after the paper engine is installed."""
from __future__ import annotations

import asyncio
import os


def attach(engine) -> None:
    from app.desk import desk

    original = engine.snapshot

    def snapshot():
        data = original()
        data["desk"] = desk.snapshot()
        return data

    engine.snapshot = snapshot
    desk.start()
    engine._log("INFO", "Multi-desk on. Wallet persisted. Ten Kraken pairs. Live blocked.")

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
