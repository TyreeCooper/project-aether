"""Historical intelligence research helpers.

These functions measure timing and subsequent price response from persisted
snapshots. They are diagnostic only and have no execution authority.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

HORIZONS_MINUTES = (5, 30, 60, 240, 1440)


def _dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _price(row: dict[str, Any]) -> float | None:
    try:
        value = float(row.get("price_usd"))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _nearest_at_or_before(
    rows: list[dict[str, Any]],
    target: datetime,
    *,
    max_age_minutes: int = 15,
) -> dict[str, Any] | None:
    candidates = []
    for row in rows:
        ts = _dt(row.get("ts"))
        px = _price(row)
        if ts is None or px is None or ts > target:
            continue
        age = (target - ts).total_seconds() / 60
        if age <= max_age_minutes:
            candidates.append((age, row))
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def _nearest_at_or_after(
    rows: list[dict[str, Any]],
    target: datetime,
    *,
    max_delay_minutes: int = 15,
) -> dict[str, Any] | None:
    candidates = []
    for row in rows:
        ts = _dt(row.get("ts"))
        px = _price(row)
        if ts is None or px is None or ts < target:
            continue
        delay = (ts - target).total_seconds() / 60
        if delay <= max_delay_minutes:
            candidates.append((delay, row))
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def _return_pct(start: float | None, end: float | None) -> float | None:
    if start is None or end is None or start <= 0:
        return None
    return round((end / start - 1) * 100, 4)


def observation_reaction(
    snapshots: list[dict[str, Any]],
    observation: dict[str, Any],
    *,
    threshold_pct: float = 0.5,
) -> dict[str, Any]:
    """Measure whether price moved before or after Aether first saw a signal.

    Classification is timing-based, not a causality claim:
    - reactive: threshold-sized move already existed in the prior 60 minutes;
    - coincident: threshold is first reached within 5 minutes after first_seen;
    - leading: threshold is first reached more than 5 minutes after first_seen;
    - no_material_move: threshold not reached within 4 hours;
    - insufficient_data: required baseline data is unavailable.
    """
    signal_at = _dt(observation.get("first_seen_at"))
    if signal_at is None:
        return {"classification": "insufficient_data", "reason": "missing_first_seen_at"}

    rows = sorted(
        [row for row in snapshots if _dt(row.get("ts")) and _price(row) is not None],
        key=lambda row: _dt(row.get("ts")) or datetime.min.replace(tzinfo=timezone.utc),
    )
    base_row = _nearest_at_or_before(rows, signal_at)
    base_px = _price(base_row or {})
    if base_px is None:
        return {
            "classification": "insufficient_data",
            "reason": "missing_baseline_price",
            "first_seen_at": signal_at.isoformat(),
        }

    prior_row = _nearest_at_or_before(
        rows,
        signal_at - timedelta(minutes=60),
        max_age_minutes=20,
    )
    prior_return = _return_pct(_price(prior_row or {}), base_px)

    forward: dict[str, float | None] = {}
    for minutes in HORIZONS_MINUTES:
        row = _nearest_at_or_after(
            rows,
            signal_at + timedelta(minutes=minutes),
            max_delay_minutes=15,
        )
        forward[f"{minutes}m_return_pct"] = _return_pct(base_px, _price(row or {}))

    threshold = abs(float(threshold_pct))
    first_move_at: datetime | None = None
    first_move_return: float | None = None
    for row in rows:
        ts = _dt(row.get("ts"))
        if ts is None or ts < signal_at or ts > signal_at + timedelta(hours=4):
            continue
        ret = _return_pct(base_px, _price(row))
        if ret is not None and abs(ret) >= threshold:
            first_move_at = ts
            first_move_return = ret
            break

    if prior_return is not None and abs(prior_return) >= threshold:
        classification = "reactive"
    elif first_move_at is None:
        classification = "no_material_move"
    elif (first_move_at - signal_at).total_seconds() <= 5 * 60:
        classification = "coincident"
    else:
        classification = "leading"

    return {
        "classification": classification,
        "threshold_pct": threshold,
        "first_seen_at": signal_at.isoformat(),
        "published_at": observation.get("published_at"),
        "source_type": observation.get("source_type"),
        "source_name": observation.get("source_name"),
        "external_id": observation.get("external_id"),
        "baseline_price": base_px,
        "prior_60m_return_pct": prior_return,
        "first_threshold_move_at": (
            first_move_at.isoformat() if first_move_at is not None else None
        ),
        "first_threshold_move_return_pct": first_move_return,
        "forward": forward,
        "note": "Timing classification only; it does not establish causality or trading alpha.",
    }


def research_observations(
    snapshots: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    *,
    threshold_pct: float = 0.5,
) -> dict[str, Any]:
    results = [
        observation_reaction(
            snapshots,
            observation,
            threshold_pct=threshold_pct,
        )
        for observation in observations
    ]
    counts: dict[str, int] = {}
    for row in results:
        key = str(row.get("classification") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    measurable = [
        row for row in results
        if row.get("classification") not in {"insufficient_data"}
    ]
    return {
        "observations": len(results),
        "measurable": len(measurable),
        "classification_counts": counts,
        "threshold_pct": abs(float(threshold_pct)),
        "results": results,
        "trade_influence_enabled": False,
        "note": "Research-only timing study. Promotion requires out-of-sample validation.",
    }
