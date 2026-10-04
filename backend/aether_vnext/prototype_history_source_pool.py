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
from datetime import datetime, timedelta
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
from aether_vnext.volatility_percentile import (
    RV14_REQUIRED_CLOSES,
    VOLATILITY_PERCENTILE_WINDOW,
)


REFERENCE_MINIMUM_BARS: Final = (
    int(VOLATILITY_PERCENTILE_WINDOW / timedelta(hours=1))
    + RV14_REQUIRED_CLOSES
    + 1
)
REFERENCE_SOURCE_IDS: Final = (
    CRYPTOCOMPARE_SOURCE_ID,
    COINBASE_SOURCE_ID,
)


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

    def health_payload(self) -> dict[str, object]:
        return {
            "service": "historical_reference",
            "service_state": "READY",
            "integrity_state": "FULL",
            "selected_source_id": self.selected_source_id,
            "selected_tier": self.selected_tier,
            "failover_active": self.selected_tier > 1,
            "source_exhausted": False,
            "attempted_source_count": len(self.attempts),
            "standby_state": "NOT_OBSERVED",
            "attempts": [
                {
                    "source_id": row.source_id,
                    "tier": row.tier,
                    "status": row.status,
                    "reason": row.reason,
                    "bar_count": row.bar_count,
                }
                for row in self.attempts
            ],
        }


class HistoricalReferenceUnavailable(RuntimeError):
    def __init__(self, attempts: tuple[HistoricalSourceAttempt, ...]):
        self.attempts = attempts
        detail = "; ".join(
            f"{row.source_id}:{row.status}:{row.reason or 'none'}"
            for row in attempts
        )
        super().__init__(f"historical_reference_exhausted:{detail}")

    def health_payload(self) -> dict[str, object]:
        return {
            "service": "historical_reference",
            "service_state": "UNAVAILABLE",
            "integrity_state": "NOT_OBSERVED",
            "selected_source_id": None,
            "selected_tier": None,
            "failover_active": False,
            "source_exhausted": True,
            "attempted_source_count": len(self.attempts),
            "standby_state": "EXHAUSTED",
            "attempts": [
                {
                    "source_id": row.source_id,
                    "tier": row.tier,
                    "status": row.status,
                    "reason": row.reason,
                    "bar_count": row.bar_count,
                }
                for row in self.attempts
            ],
        }


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


def select_persisted_reference_history(
    rows: tuple[PrototypeMarketBar, ...],
    *,
    minimum_bars: int = REFERENCE_MINIMUM_BARS,
) -> HistoricalReferenceResult:
    """Select one complete persisted reference source by policy tier.

    Persisted bars from different providers are never blended at identical timestamps.
    This lets failover and later primary recovery coexist in the ledger without
    manufacturing a composite historical tape.
    """
    if minimum_bars < 1:
        raise ValueError("minimum_bars must be positive")
    attempts: list[HistoricalSourceAttempt] = []
    tier_by_source = {
        CRYPTOCOMPARE_SOURCE_ID: 1,
        COINBASE_SOURCE_ID: 2,
    }
    for source_id in REFERENCE_SOURCE_IDS:
        source_rows = tuple(
            sorted(
                (row for row in rows if row.source_id == source_id),
                key=lambda row: row.bucket_open_utc,
            )
        )
        if len(source_rows) >= minimum_bars:
            attempts.append(HistoricalSourceAttempt(
                source_id=source_id,
                tier=tier_by_source[source_id],
                status="READY",
                reason=None,
                bar_count=len(source_rows),
            ))
            return HistoricalReferenceResult(
                bars=source_rows,
                selected_source_id=source_id,
                selected_tier=tier_by_source[source_id],
                attempts=tuple(attempts),
            )
        attempts.append(HistoricalSourceAttempt(
            source_id=source_id,
            tier=tier_by_source[source_id],
            status="INSUFFICIENT",
            reason=f"persisted_bar_count:{len(source_rows)}<{minimum_bars}",
            bar_count=len(source_rows),
        ))
    raise HistoricalReferenceUnavailable(tuple(attempts))
