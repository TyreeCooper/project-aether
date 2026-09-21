"""Start the one-account desk after the paper engine is installed."""
from __future__ import annotations


def attach(engine) -> None:
    from app.desk import desk

    original = engine.snapshot

    def snapshot():
        data = original()
        data["desk"] = desk.snapshot()
        return data

    engine.snapshot = snapshot
    desk.start()
    engine._log("INFO", "Multi-desk on. One USD book. Ten Kraken pairs. Live blocked.")
