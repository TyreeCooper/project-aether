"""Provider-wide discovery and Top-100 focus ranking for AETHER vNext.

This module is deliberately pre-Scout. It ranks market opportunity only; it cannot
create setups, tickets, Risk decisions, fills, or live orders. Provider Top 100 means
"deserves deeper attention", never "must trade".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Iterable


UTC = timezone.utc
FOCUS_LIMIT = 100

# Transparent prototype focus weights. These are provider-relative discovery
# weights, not trading-strategy or Risk weights.
DISCOVERY_WEIGHTS = {
    "movement": 0.40,
    "liquidity": 0.30,
    "spread_quality": 0.20,
    "data_quality": 0.10,
}


@dataclass(frozen=True, slots=True)
class DiscoveryInstrument:
    provider: str
    symbol: str
    market_data_symbol: str
    asset_class: str
    name: str | None = None
    execution_symbol: str | None = None
    product_code: str | None = None
    base_currency: str | None = None
    quote_currency: str | None = None
    quantity_step: float | None = None
    minimum_quantity: float | None = None
    minimum_notional: float | None = None
    tick_size: float | None = None
    active: bool = True
    price: float | None = None
    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    volume: float | None = None
    open_interest: float | None = None
    bid: float | None = None
    ask: float | None = None
    change_pct: float | None = None
    observed_at_utc: datetime | None = None
    source: str = ""
    feed_class: str = "REFERENCE"
    execution_quality: bool = False

    def __post_init__(self) -> None:
        for name in ("provider", "symbol", "market_data_symbol", "asset_class"):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValueError(f"{name} is required")
        if self.observed_at_utc is not None and self.observed_at_utc.tzinfo is None:
            raise ValueError("observed_at_utc must be timezone-aware")
        for name in (
            "price", "open_price", "high_price", "low_price",
            "volume", "open_interest", "bid", "ask", "change_pct",
            "quantity_step", "minimum_quantity", "minimum_notional", "tick_size",
        ):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not math.isfinite(float(value))
            ):
                raise ValueError(f"{name} must be finite when present")


@dataclass(frozen=True, slots=True)
class RankedInstrument:
    rank: int
    provider: str
    symbol: str
    market_data_symbol: str
    execution_symbol: str | None
    asset_class: str
    name: str | None
    product_code: str | None
    base_currency: str | None
    quote_currency: str | None
    quantity_step: float | None
    minimum_quantity: float | None
    minimum_notional: float | None
    tick_size: float | None
    score: float
    movement_score: float
    liquidity_score: float
    spread_quality_score: float
    data_quality_score: float
    price: float | None
    bid: float | None
    ask: float | None
    change_pct: float
    volume: float | None
    open_interest: float | None
    spread_bps: float | None
    observed_at_utc: datetime | None
    source: str
    feed_class: str
    execution_quality: bool


@dataclass(frozen=True, slots=True)
class ProviderFocus:
    provider: str
    catalog_count: int
    eligible_count: int
    top100: tuple[RankedInstrument, ...]


def _eligible(row: DiscoveryInstrument) -> bool:
    if not row.active:
        return False
    price_available = row.price is not None and float(row.price) > 0.0
    activity_available = any(
        value is not None and float(value) > 0.0
        for value in (row.volume, row.open_interest)
    )
    if not price_available and not activity_available:
        return False
    if row.price is not None and float(row.price) <= 0.0:
        return False
    if row.volume is not None and float(row.volume) < 0.0:
        return False
    if row.open_interest is not None and float(row.open_interest) < 0.0:
        return False
    if row.bid is not None and float(row.bid) <= 0.0:
        return False
    if row.ask is not None and float(row.ask) <= 0.0:
        return False
    if (
        row.bid is not None
        and row.ask is not None
        and float(row.ask) < float(row.bid)
    ):
        return False
    return True


def _percentile_scores(values: dict[str, float]) -> dict[str, float]:
    """Return tie-aware percentile scores in O(n log n), not O(n²).

    Equal values receive the average rank of their contiguous tie group. The
    previous implementation rescanned the full ordered universe for every
    instrument, which becomes prohibitive for 10k+ equity catalogs.
    """
    if not values:
        return {}
    if len(values) == 1:
        return {key: 50.0 for key in values}

    ordered = sorted(values.items(), key=lambda item: (item[1], item[0]))
    denominator = len(ordered) - 1
    scores: dict[str, float] = {}
    start = 0
    while start < len(ordered):
        value = ordered[start][1]
        end = start + 1
        while end < len(ordered) and ordered[end][1] == value:
            end += 1
        average_position = (start + (end - 1)) / 2.0
        percentile = (average_position / denominator) * 100.0
        for index in range(start, end):
            scores[ordered[index][0]] = percentile
        start = end
    return scores


def _spread_bps(row: DiscoveryInstrument) -> float | None:
    if row.bid is None or row.ask is None:
        return None
    bid = float(row.bid)
    ask = float(row.ask)
    midpoint = (bid + ask) / 2.0
    if midpoint <= 0.0:
        return None
    return ((ask - bid) / midpoint) * 10_000.0


def _change_pct(row: DiscoveryInstrument) -> float:
    if row.change_pct is not None:
        return float(row.change_pct)
    if row.open_price is None or row.price is None:
        return 0.0
    open_price = float(row.open_price)
    if open_price <= 0.0:
        return 0.0
    return ((float(row.price) - open_price) / open_price) * 100.0


def _quality(row: DiscoveryInstrument) -> float:
    fields = (
        row.price,
        row.open_price,
        row.high_price,
        row.low_price,
        row.volume,
        row.open_interest,
        row.bid,
        row.ask,
    )
    present = sum(value is not None for value in fields)
    return (present / len(fields)) * 100.0


def rank_provider_catalog(
    rows: Iterable[DiscoveryInstrument],
    *,
    provider: str,
    limit: int = FOCUS_LIMIT,
) -> ProviderFocus:
    if limit <= 0:
        raise ValueError("limit must be positive")
    provider_name = str(provider).strip()
    if not provider_name:
        raise ValueError("provider is required")

    catalog = tuple(row for row in rows if row.provider == provider_name)
    eligible = tuple(row for row in catalog if _eligible(row))
    if not eligible:
        return ProviderFocus(
            provider=provider_name,
            catalog_count=len(catalog),
            eligible_count=0,
            top100=(),
        )

    keys = {
        row.market_data_symbol: row
        for row in eligible
    }
    if len(keys) != len(eligible):
        raise ValueError("provider catalog contains duplicate market_data_symbol")

    movement = _percentile_scores({
        key: abs(_change_pct(row))
        for key, row in keys.items()
    })
    known_liquidity = {
        key: math.log1p(
            max(
                0.0,
                float(row.volume or 0.0),
                float(row.open_interest or 0.0),
            )
        )
        for key, row in keys.items()
        if row.volume is not None or row.open_interest is not None
    }
    liquidity_known_scores = _percentile_scores(known_liquidity)
    liquidity = {
        key: liquidity_known_scores.get(key, 50.0)
        for key in keys
    }

    known_spreads = {
        key: -float(spread)
        for key, row in keys.items()
        if (spread := _spread_bps(row)) is not None
    }
    spread_known_scores = _percentile_scores(known_spreads)
    spread_quality = {
        key: spread_known_scores.get(key, 50.0)
        for key in keys
    }

    staged: list[tuple[DiscoveryInstrument, float, float, float, float, float]] = []
    for key, row in keys.items():
        data_quality = _quality(row)
        score = (
            DISCOVERY_WEIGHTS["movement"] * movement[key]
            + DISCOVERY_WEIGHTS["liquidity"] * liquidity[key]
            + DISCOVERY_WEIGHTS["spread_quality"] * spread_quality[key]
            + DISCOVERY_WEIGHTS["data_quality"] * data_quality
        )
        staged.append((
            row,
            score,
            movement[key],
            liquidity[key],
            spread_quality[key],
            data_quality,
        ))

    staged.sort(
        key=lambda item: (
            -item[1],
            -abs(_change_pct(item[0])),
            -max(
                0.0,
                float(item[0].volume or 0.0),
                float(item[0].open_interest or 0.0),
            ),
            item[0].symbol,
        )
    )

    ranked = tuple(
        RankedInstrument(
            rank=index,
            provider=provider_name,
            symbol=row.symbol,
            market_data_symbol=row.market_data_symbol,
            execution_symbol=row.execution_symbol,
            asset_class=row.asset_class,
            name=row.name,
            product_code=row.product_code,
            base_currency=row.base_currency,
            quote_currency=row.quote_currency,
            quantity_step=row.quantity_step,
            minimum_quantity=row.minimum_quantity,
            minimum_notional=row.minimum_notional,
            tick_size=row.tick_size,
            score=score,
            movement_score=movement_score,
            liquidity_score=liquidity_score,
            spread_quality_score=spread_score,
            data_quality_score=data_quality,
            price=(None if row.price is None else float(row.price)),
            bid=(None if row.bid is None else float(row.bid)),
            ask=(None if row.ask is None else float(row.ask)),
            change_pct=_change_pct(row),
            volume=(None if row.volume is None else float(row.volume)),
            open_interest=(
                None if row.open_interest is None else float(row.open_interest)
            ),
            spread_bps=_spread_bps(row),
            observed_at_utc=row.observed_at_utc,
            source=row.source,
            feed_class=row.feed_class,
            execution_quality=bool(row.execution_quality),
        )
        for index, (
            row,
            score,
            movement_score,
            liquidity_score,
            spread_score,
            data_quality,
        ) in enumerate(staged[:limit], start=1)
    )
    return ProviderFocus(
        provider=provider_name,
        catalog_count=len(catalog),
        eligible_count=len(eligible),
        top100=ranked,
    )


def eligible_catalog_payload(
    rows: Iterable[DiscoveryInstrument],
    *,
    provider: str,
) -> list[dict[str, object]]:
    """Serialize the full eligible provider catalog without turning rank into a gate."""
    provider_name = str(provider).strip()
    if not provider_name:
        raise ValueError("provider is required")
    eligible = sorted(
        (
            row for row in rows
            if row.provider == provider_name and _eligible(row)
        ),
        key=lambda row: (row.market_data_symbol, row.symbol),
    )
    return [
        {
            "provider": row.provider,
            "symbol": row.symbol,
            "market_data_symbol": row.market_data_symbol,
            "execution_symbol": row.execution_symbol,
            "asset_class": row.asset_class,
            "name": row.name,
            "product_code": row.product_code,
            "base_currency": row.base_currency,
            "quote_currency": row.quote_currency,
            "quantity_step": row.quantity_step,
            "minimum_quantity": row.minimum_quantity,
            "minimum_notional": row.minimum_notional,
            "tick_size": row.tick_size,
            "price": None if row.price is None else float(row.price),
            "bid": None if row.bid is None else float(row.bid),
            "ask": None if row.ask is None else float(row.ask),
            "change_pct": _change_pct(row),
            "volume": None if row.volume is None else float(row.volume),
            "open_interest": (
                None if row.open_interest is None else float(row.open_interest)
            ),
            "spread_bps": _spread_bps(row),
            "observed_at_utc": (
                None
                if row.observed_at_utc is None
                else row.observed_at_utc.astimezone(UTC).isoformat()
            ),
            "source": row.source,
            "feed_class": row.feed_class,
            "execution_quality": bool(row.execution_quality),
        }
        for row in eligible
    ]


def focus_payload(focus: ProviderFocus) -> dict[str, object]:
    return {
        "provider": focus.provider,
        "catalog_count": focus.catalog_count,
        "eligible_count": focus.eligible_count,
        "focus_count": len(focus.top100),
        "top100": [
            {
                "rank": row.rank,
                "symbol": row.symbol,
                "market_data_symbol": row.market_data_symbol,
                "execution_symbol": row.execution_symbol,
                "asset_class": row.asset_class,
                "name": row.name,
                "product_code": row.product_code,
                "base_currency": row.base_currency,
                "quote_currency": row.quote_currency,
                "quantity_step": row.quantity_step,
                "minimum_quantity": row.minimum_quantity,
                "minimum_notional": row.minimum_notional,
                "tick_size": row.tick_size,
                "bid": row.bid,
                "ask": row.ask,
                "score": row.score,
                "movement_score": row.movement_score,
                "liquidity_score": row.liquidity_score,
                "spread_quality_score": row.spread_quality_score,
                "data_quality_score": row.data_quality_score,
                "price": row.price,
                "change_pct": row.change_pct,
                "volume": row.volume,
                "open_interest": row.open_interest,
                "spread_bps": row.spread_bps,
                "observed_at_utc": (
                    None
                    if row.observed_at_utc is None
                    else row.observed_at_utc.astimezone(UTC).isoformat()
                ),
                "source": row.source,
                "feed_class": row.feed_class,
                "execution_quality": row.execution_quality,
            }
            for row in focus.top100
        ],
    }
