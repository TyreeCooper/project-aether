"""Aether asset intelligence primitives.

This layer describes opportunity, context, source health, and observed trade
capture. It does not create orders. Missing external intelligence is represented
as unavailable, never silently as neutral.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import sqrt
from typing import Any

SOURCE_REGISTRY: tuple[dict[str, Any], ...] = (
    {"id": "kraken", "name": "Kraken", "type": "market", "tier": "A", "status": "connected"},
    {"id": "binance_us", "name": "Binance.US", "type": "watch_market", "tier": "A", "status": "connected"},
    {"id": "federal_reserve", "name": "Federal Reserve", "type": "macro_official", "tier": "A", "status": "planned"},
    {"id": "bls", "name": "U.S. Bureau of Labor Statistics", "type": "macro_official", "tier": "A", "status": "planned"},
    {"id": "bea", "name": "U.S. Bureau of Economic Analysis", "type": "macro_official", "tier": "A", "status": "planned"},
    {"id": "forex_factory", "name": "Forex Factory", "type": "calendar_aggregator", "tier": "B", "status": "planned"},
    {"id": "gdelt", "name": "GDELT", "type": "news_discovery", "tier": "B", "status": "planned"},
    {"id": "asset_official", "name": "Official asset/project channels", "type": "asset_official", "tier": "A", "status": "planned"},
    {"id": "community", "name": "Verified asset communities", "type": "community", "tier": "B", "status": "planned"},
)

def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def opportunity_24h(asset: dict[str, Any]) -> dict[str, Any]:
    last = _f(asset.get("mark") or asset.get("last"))
    open_ = _f(asset.get("open_24h"))
    high = _f(asset.get("high_24h"))
    low = _f(asset.get("low_24h"))
    bid = _f(asset.get("bid"))
    ask = _f(asset.get("ask"))
    net = last - open_ if last > 0 and open_ > 0 else 0.0
    net_pct = net / open_ * 100 if open_ > 0 else 0.0
    range_usd = high - low if high > 0 and low > 0 and high >= low else 0.0
    range_pct = range_usd / open_ * 100 if open_ > 0 else 0.0
    position = (last - low) / range_usd * 100 if range_usd > 0 else None
    upside = high - open_ if open_ > 0 and high > 0 else 0.0
    downside = low - open_ if open_ > 0 and low > 0 else 0.0
    mid = (bid + ask) / 2 if bid > 0 and ask > 0 else 0.0
    spread_bps = (ask - bid) / mid * 10_000 if mid > 0 and ask >= bid else None
    return {
        "current": last or None,
        "open": open_ or None,
        "high": high or None,
        "low": low or None,
        "net_move": round(net, 8),
        "net_change_pct": round(net_pct, 4),
        "opportunity_range": round(range_usd, 8),
        "opportunity_range_pct": round(range_pct, 4),
        "upside_excursion": round(upside, 8),
        "downside_excursion": round(downside, 8),
        "range_position_pct": None if position is None else round(position, 2),
        "volume": _f(asset.get("volume_24h")) or None,
        "vwap": _f(asset.get("vwap_24h")) or None,
        "trades": int(_f(asset.get("trades_24h"))),
        "spread_bps": None if spread_bps is None else round(spread_bps, 3),
        "label": "movement opportunity, not guaranteed capturable profit",
    }

def window_stats(bars: list[dict[str, Any]], minutes: int) -> dict[str, Any]:
    rows = bars[-max(1, int(minutes)):]
    if not rows:
        return {"minutes": minutes, "bars": 0}
    first = _f(rows[0].get("open") or rows[0].get("close"))
    last = _f(rows[-1].get("close"))
    high = max((_f(x.get("high")) for x in rows), default=0.0)
    low = min((_f(x.get("low")) for x in rows if _f(x.get("low")) > 0), default=0.0)
    move = last - first if first > 0 else 0.0
    return {
        "minutes": minutes,
        "bars": len(rows),
        "open": first or None,
        "close": last or None,
        "high": high or None,
        "low": low or None,
        "change_pct": round(move / first * 100, 4) if first > 0 else 0.0,
        "range_pct": round((high - low) / first * 100, 4) if first > 0 and low > 0 and high >= low else 0.0,
    }

def counted_window_stats(
    bars: list[dict[str, Any]],
    count: int,
    label: str,
) -> dict[str, Any]:
    rows = bars[-max(1, int(count)):]
    if not rows:
        return {"label": label, "bars": 0}
    first = _f(rows[0].get("open") or rows[0].get("close"))
    last = _f(rows[-1].get("close"))
    high = max((_f(x.get("high")) for x in rows), default=0.0)
    low = min((_f(x.get("low")) for x in rows if _f(x.get("low")) > 0), default=0.0)
    return {
        "label": label,
        "bars": len(rows),
        "open": first or None,
        "close": last or None,
        "high": high or None,
        "low": low or None,
        "change_pct": round((last / first - 1) * 100, 4) if first > 0 else 0.0,
        "range_pct": round((high - low) / first * 100, 4)
        if first > 0 and low > 0 and high >= low
        else 0.0,
    }


def pearson_from_bars(target: list[dict[str, Any]], benchmark: list[dict[str, Any]], max_points: int = 240) -> float | None:
    a = {int(x.get("ts", 0)): _f(x.get("close")) for x in target[-max_points:]}
    b = {int(x.get("ts", 0)): _f(x.get("close")) for x in benchmark[-max_points:]}
    keys = sorted(set(a).intersection(b))
    if len(keys) < 20:
        return None
    ra: list[float] = []
    rb: list[float] = []
    for prev, cur in zip(keys, keys[1:]):
        if a[prev] > 0 and b[prev] > 0:
            ra.append(a[cur] / a[prev] - 1)
            rb.append(b[cur] / b[prev] - 1)
    if len(ra) < 15:
        return None
    ma = sum(ra) / len(ra)
    mb = sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra)
    vb = sum((y - mb) ** 2 for y in rb)
    den = sqrt(va * vb)
    return round(cov / den, 4) if den > 1e-18 else None

def _dt(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def risk_state(
    events: list[dict[str, Any]] | None = None,
    *,
    calendar_connected: bool = False,
    community: dict[str, Any] | None = None,
    news: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = list(events or [])
    now = datetime.now(timezone.utc)
    active: list[dict[str, Any]] = []
    for event in rows:
        if str(event.get("state")) not in {"blackout", "restricted", "caution"}:
            continue
        start = _dt(event.get("window_start"))
        end = _dt(event.get("window_end"))
        if start and end and start <= now <= end:
            active.append(event)
    state = (
        "restricted"
        if any(str(x.get("state")) in {"blackout", "restricted"} for x in active)
        else "caution"
        if active
        else "normal"
    )
    return {
        "state": state,
        "active_events": active,
        "new_entries_allowed": state != "restricted",
        "calendar_connected": bool(calendar_connected),
        "note": (
            "No macro/crypto event calendar connected yet; state is market-data-only."
            if not calendar_connected
            else None
        ),
    }


def move_attribution(
    book: Any,
    books: list[Any],
    opportunity: dict[str, Any],
    cross_asset: dict[str, Any],
    events: list[dict[str, Any]] | None,
    calendar_connected: bool,
    news: dict[str, Any] | None = None,
) -> dict[str, Any]:
    drivers: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    move = _f(opportunity.get("net_change_pct"))

    if book.id != "btc":
        btc = next((b for b in books if getattr(b, "id", "") == "btc"), None)
        if btc is not None:
            btc_move = _f(opportunity_24h(btc.view()).get("net_change_pct"))
            corr = cross_asset.get("btc_correlation_4h")
            if (
                corr is not None
                and float(corr) >= 0.4
                and move * btc_move > 0
                and abs(btc_move) >= 0.5
            ):
                drivers.append(
                    {
                        "type": "broad_market",
                        "label": "Broad crypto / BTC-aligned move",
                        "confidence_pct": min(90, round(50 + float(corr) * 40)),
                        "evidence": {
                            "btc_change_24h_pct": round(btc_move, 4),
                            "btc_correlation_4h": corr,
                        },
                    }
                )

    if calendar_connected:
        for event in events or []:
            scheduled = _dt(event.get("scheduled_at"))
            if not scheduled or not (now - timedelta(hours=24) <= scheduled <= now):
                continue
            if str(event.get("country")) != "USD":
                continue
            impact = str(event.get("impact") or "").lower()
            if impact not in {"high", "medium"}:
                continue
            hours = max((now - scheduled).total_seconds() / 3600, 0.0)
            base = 72 if impact == "high" else 52
            confidence = max(30, round(base - min(hours, 24) * 1.2))
            drivers.append(
                {
                    "type": "macro_event",
                    "label": str(event.get("title") or "USD macro event"),
                    "confidence_pct": confidence,
                    "evidence": {
                        "impact": str(event.get("impact") or ""),
                        "scheduled_at": event.get("scheduled_at"),
                        "source": event.get("source"),
                        "officially_verified": bool(event.get("verified_official")),
                    },
                }
            )

    # News remains shadow context. Multiple independent domains can support a
    # candidate explanation, but cannot establish causality or create an order.
    news_row = news or {}
    if str(news_row.get("status") or "") == "shadow":
        domains = int(_f(news_row.get("independent_domains")))
        articles = int(_f(news_row.get("articles_analyzed")))
        narratives = list(news_row.get("narratives") or [])
        if articles > 0 and domains >= 2:
            confidence = min(55, 30 + min(domains, 5) * 5)
            drivers.append(
                {
                    "type": "asset_news",
                    "label": "Asset-specific news cluster",
                    "confidence_pct": confidence,
                    "evidence": {
                        "articles_analyzed": articles,
                        "independent_domains": domains,
                        "top_narratives": narratives[:3],
                        "claims_verified": bool(news_row.get("claims_verified")),
                        "source_mode": "discovery_shadow",
                    },
                }
            )

    pos = opportunity.get("range_position_pct")
    rng = _f(opportunity.get("opportunity_range_pct"))
    if pos is not None and rng >= 2.0:
        if float(pos) >= 80 and move > 0:
            drivers.append(
                {
                    "type": "technical",
                    "label": "Price holding near 24h range high",
                    "confidence_pct": 45,
                    "evidence": {"range_position_pct": pos, "range_24h_pct": rng},
                }
            )
        elif float(pos) <= 20 and move < 0:
            drivers.append(
                {
                    "type": "technical",
                    "label": "Price holding near 24h range low",
                    "confidence_pct": 45,
                    "evidence": {"range_position_pct": pos, "range_24h_pct": rng},
                }
            )

    drivers.sort(key=lambda x: int(x.get("confidence_pct") or 0), reverse=True)
    return {
        "status": "candidate_drivers" if drivers else "unavailable",
        "drivers": drivers[:6],
        "note": (
            "Candidate explanations are timing/correlation evidence, not claims of causation."
            if drivers
            else "No evidence-backed driver candidates are available yet."
        ),
    }

def source_registry(calendar_connected: bool = False) -> list[dict[str, Any]]:
    rows = [dict(x) for x in SOURCE_REGISTRY]
    for row in rows:
        if row["id"] == "forex_factory" and calendar_connected:
            row["status"] = "connected"
    return rows

def asset_context(
    book: Any,
    books: list[Any],
    *,
    events: list[dict[str, Any]] | None = None,
    calendar_connected: bool = False,
    community: dict[str, Any] | None = None,
    news: dict[str, Any] | None = None,
) -> dict[str, Any]:
    view = book.view()
    bars = list(book.bars)
    bars_1h = list(getattr(book, "bars_1h", []))
    opp = opportunity_24h(view)
    btc = next((b for b in books if str(getattr(b, "id", "")) == "btc"), None)
    btc_corr = None
    btc_relative = None
    if btc is not None and btc is not book:
        btc_corr = pearson_from_bars(bars, list(btc.bars))
        btc_opp = opportunity_24h(btc.view())
        btc_relative = round(_f(opp.get("net_change_pct")) - _f(btc_opp.get("net_change_pct")), 4)
    cross_asset = {
        "btc_correlation_4h": 1.0 if book.id == "btc" else btc_corr,
        "relative_strength_vs_btc_24h_pct": 0.0 if book.id == "btc" else btc_relative,
    }
    return {
        "opportunity_24h": opp,
        "windows": {
            "1h": window_stats(bars, 60),
            "4h": window_stats(bars, 240),
            "12h": window_stats(bars, 720),
            "3d": counted_window_stats(bars_1h, 72, "3d"),
            "7d": counted_window_stats(bars_1h, 168, "7d"),
            "30d": counted_window_stats(bars_1h, 720, "30d"),
        },
        "cross_asset": cross_asset,
        "attribution": move_attribution(
            book,
            books,
            opp,
            cross_asset,
            events,
            calendar_connected,
            news=news,
        ),
        "community": community or {
            "status": "unavailable", "sentiment": None, "velocity": None,
            "discussion_volume_ratio": None, "narratives": [],
            "note": "Verified community sources are not connected yet; unavailable is not neutral.",
        },
        "news": news or {
            "status": "unavailable",
            "shadow_only": True,
            "trade_influence_enabled": False,
            "articles_analyzed": 0,
            "independent_domains": 0,
            "narratives": [],
            "note": "Asset-specific news context is not available; unavailable is not neutral.",
        },
        "risk": risk_state(events, calendar_connected=calendar_connected),
    }

def floor_intelligence(
    books: list[Any],
    *,
    events: list[dict[str, Any]] | None = None,
    calendar_connected: bool = False,
    community_cache: dict[str, dict[str, Any]] | None = None,
    news_cache: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = []
    for book in books:
        ctx = asset_context(
            book,
            books,
            events=events,
            calendar_connected=calendar_connected,
            community=(community_cache or {}).get(str(book.id)),
            news=(news_cache or {}).get(str(book.id)),
        )
        opp = ctx["opportunity_24h"]
        rows.append({
            "id": book.id, "symbol": book.symbol, "pair": book.pair,
            "price": opp.get("current"), "change_24h_pct": opp.get("net_change_pct"),
            "range_24h_pct": opp.get("opportunity_range_pct"), "range_24h": opp.get("opportunity_range"),
            "volume_24h": opp.get("volume"), "spread_bps": opp.get("spread_bps"),
            "relative_strength_vs_btc_24h_pct": ctx["cross_asset"].get("relative_strength_vs_btc_24h_pct"),
            "risk_state": ctx["risk"]["state"],
        })
    return {
        "assets": rows,
        "opportunity_ranking": sorted(rows, key=lambda x: _f(x.get("range_24h_pct")), reverse=True),
        "risk": risk_state(events, calendar_connected=calendar_connected),
        "sources": source_registry(calendar_connected=calendar_connected),
        "methodology": {
            "opportunity": "Kraken 24h high-low range; not claimed profit",
            "cross_asset": "rolling 1m return correlation where enough common bars exist",
            "news_attribution": "not active until verified feeds are connected",
            "community": "not active until verified source bundles are connected",
        },
    }
