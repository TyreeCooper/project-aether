"""Resilient historical reference source pool for PAPER feature warm-up.

This module supplies historical FEATURE data only. It never creates executable market
truth and never participates in Market Fabric price authority.

Policy:
- Tier 1: CryptoCompare exchange=Kraken history with conversion disabled.
- Tier 2: Coinbase Exchange USD candles when an online matching product exists.
- Source failures are recorded and the next source is attempted.
- Bars keep their original source_id/source_ref provenance.
- No missing bars are synthesized and no source is relabeled as another venue.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from aether_vnext.coinbase_prototype_history import (
    COINBASE_SOURCE_ID,
    fetch_coinbase_hourly_history,
    fetch_coinbase_public_products,
)
from aether_vnext.prototype_history_sources import (
    CRYPTOCOMPARE_SOURCE_ID,
    fetch_cryptocompare_kraken_hourly,
)
from aether_vnext.prototype_market_history import PrototypeMarketBar


REFERENCE_MINIMUM_BARS: Final = 2200


@dataclass(frozen=True, slots=True)
class HistoricalSourceAttempt:
    source_id: str
    tier: int
    status: str
    reason: str | None
    bar_count: int


@dataclass(frozen=True, slots=True)
class HistoricalReferenceResult:
    bars: tuple[PrototypeMarketBar, ...]
    selected_source_id: str
    selected_tier: int
    attempts: tuple[HistoricalSourceAttempt, ...]


class HistoricalReferenceUnavailable(RuntimeError):
    def __init__(self, attempts: tuple[HistoricalSourceAttempt, ...]):
        self.attempts = attempts
        detail = "; ".join(
            f"{row.source_id}:{row.status}:{row.reason or 'none'}"
            for row in attempts
        )
        super().__init__(f"historical_reference_exhausted:{detail}")


async def fetch_historical_reference_pool(
    *,
    asset_id: str,
    asset_symbol: str,
    end_at_utc: datetime,
    minimum_bars: int = REFERENCE_MINIMUM_BARS,
    timeout_s: float = 20.0,
) -> HistoricalReferenceResult:
    """Return the first complete historical reference source by policy tier."""
    if end_at_utc.tzinfo is None:
        raise ValueError("end_at_utc must be timezone-aware")
    if minimum_bars < 1:
        raise ValueError("minimum_bars must be positive")
    asset = str(asset_id).strip().lower()
    symbol = str(asset_symbol).strip().upper()
    if not asset or not symbol:
        raise ValueError("asset_id and asset_symbol are required")

    attempts: list[HistoricalSourceAttempt] = []

    try:
        bars = await fetch_cryptocompare_kraken_hourly(
            asset_id=asset,
            asset_symbol=symbol,
            end_at_utc=end_at_utc,
            minimum_bars=minimum_bars,
            timeout_s=timeout_s,
        )
        attempts.append(HistoricalSourceAttempt(
            source_id=CRYPTOCOMPARE_SOURCE_ID,
            tier=1,
            status="READY",
            reason=None,
            bar_count=len(bars),
        ))
        return HistoricalReferenceResult(
            bars=tuple(bars),
            selected_source_id=CRYPTOCOMPARE_SOURCE_ID,
            selected_tier=1,
            attempts=tuple(attempts),
        )
    except Exception as exc:
        attempts.append(HistoricalSourceAttempt(
            source_id=CRYPTOCOMPARE_SOURCE_ID,
            tier=1,
            status="FAILED",
            reason=f"{type(exc).__name__}:{exc}",
            bar_count=0,
        ))

    try:
        products = await fetch_coinbase_public_products(timeout_s=timeout_s)
        product = products.get((symbol, "USD"))
        if not product:
            attempts.append(HistoricalSourceAttempt(
                source_id=COINBASE_SOURCE_ID,
                tier=2,
                status="UNAVAILABLE",
                reason="matching_usd_product_not_observed",
                bar_count=0,
            ))
        else:
            bars = await fetch_coinbase_hourly_history(
                asset_id=asset,
                coinbase_product=product,
                end_at_utc=end_at_utc,
                minimum_bars=minimum_bars,
                timeout_s=timeout_s,
            )
            attempts.append(HistoricalSourceAttempt(
                source_id=COINBASE_SOURCE_ID,
                tier=2,
                status="READY",
                reason=None,
                bar_count=len(bars),
            ))
            return HistoricalReferenceResult(
                bars=tuple(bars),
                selected_source_id=COINBASE_SOURCE_ID,
                selected_tier=2,
                attempts=tuple(attempts),
            )
    except Exception as exc:
        attempts.append(HistoricalSourceAttempt(
            source_id=COINBASE_SOURCE_ID,
            tier=2,
            status="FAILED",
            reason=f"{type(exc).__name__}:{exc}",
            bar_count=0,
        ))

    raise HistoricalReferenceUnavailable(tuple(attempts))
