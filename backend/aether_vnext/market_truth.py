"""Market Data Truth helpers from the Master Blueprint.

Freshness thresholds remain policy/config inputs; this module does not invent
asset-specific stale tolerances.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from aether_vnext.domain import MarketObservation, QualityState, SessionState


def observation_is_valid(
    observation: MarketObservation,
    *,
    max_age_ms: int,
) -> bool:
    """Hard market-validity gate shared by FIRE/READY/OPEN.

    Healthy or degraded observations may be usable if still fresh and not
    crossed. stale/invalid quality states are never valid.
    """
    if max_age_ms < 0:
        raise ValueError("max_age_ms must be non-negative")
    if observation.quality_state in {QualityState.STALE, QualityState.INVALID}:
        return False
    if observation.age_ms > max_age_ms:
        return False
    if observation.session_state in {
        SessionState.CLOSED,
        SessionState.MAINTENANCE,
        SessionState.HALT,
    }:
        return False
    if observation.bid is not None and observation.ask is not None:
        if observation.bid > observation.ask:
            return False
    return observation.mark is not None and observation.mark > 0


def bar_is_closed(
    *,
    bar_open_utc: datetime,
    interval: timedelta,
    observation_exchange_ts: datetime | None,
    observation_received_ts: datetime,
    session_close_utc: datetime | None = None,
    received_grace: timedelta = timedelta(seconds=2),
) -> bool:
    """Binding completed-bar law used by replay, paper, and eventual live paths."""
    if interval.total_seconds() <= 0:
        raise ValueError("interval must be positive")

    close_utc = bar_open_utc + interval

    if session_close_utc is not None and session_close_utc < close_utc:
        close_utc = session_close_utc

    if observation_exchange_ts is not None:
        return observation_exchange_ts >= close_utc

    return observation_received_ts >= close_utc + received_grace
