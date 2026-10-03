"""Bridge official AETHER Consensus Tape truth into the existing market gate.

This module does not submit orders. FULL Tape quorum may project a canonical healthy
MarketObservation for strategy evaluation. Lower-confidence states remain observable
but fail closed for new-entry authority.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import hashlib
from statistics import mean
from typing import Sequence

from aether_vnext.calendars import CalendarDecision, calendar_decision
from aether_vnext.domain import MarketObservation, QualityState
from aether_vnext.tape import (
    TapeCompositeObservation,
    TapeConsensusState,
    TapeSourceObservation,
)


TAPE_MARKET_SOURCE_ID = "aether_consensus_tape"
TAPE_MARKET_DATA_VERSION = "aether_consensus_tape_v1"


@dataclass(frozen=True, slots=True)
class TapeMarketProjection:
    observation: MarketObservation | None
    strategy_ready: bool
    reason: str


def _latest_accepted_by_source(
    composite: TapeCompositeObservation,
    observations: Sequence[TapeSourceObservation],
) -> tuple[TapeSourceObservation, ...]:
    allowed = set(composite.accepted_source_ids)
    by_source: dict[str, TapeSourceObservation] = {}
    for row in observations:
        if row.asset_id != composite.asset_id:
            raise ValueError("Tape source/composite asset mismatch")
        if row.source_id not in allowed:
            continue
        prior = by_source.get(row.source_id)
        if prior is None or (
            row.received_ts,
            row.observation_id,
        ) > (
            prior.received_ts,
            prior.observation_id,
        ):
            by_source[row.source_id] = row
    return tuple(by_source[key] for key in sorted(by_source))


def project_tape_market_observation(
    composite: TapeCompositeObservation,
    *,
    source_observations: Sequence[TapeSourceObservation],
    calendar: CalendarDecision,
    as_of_utc: datetime,
) -> TapeMarketProjection:
    if as_of_utc.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")

    if composite.state is TapeConsensusState.NOT_OBSERVED:
        return TapeMarketProjection(None, False, "tape_not_observed")
    if composite.state is TapeConsensusState.CONTESTED:
        return TapeMarketProjection(None, False, "tape_contested")
    if composite.composite_mark is None:
        return TapeMarketProjection(None, False, "tape_composite_mark_missing")

    accepted = _latest_accepted_by_source(composite, source_observations)
    if len(accepted) != composite.source_count:
        return TapeMarketProjection(
            None,
            False,
            "tape_accepted_source_lineage_incomplete",
        )

    bbo_rows = tuple(
        row for row in accepted
        if row.bid is not None and row.ask is not None
    )
    if len(bbo_rows) < composite.quorum_required:
        # A Tape mark can still be displayed at lower coverage, but the strategy
        # market gate requires a full independent BBO quorum.
        return TapeMarketProjection(
            None,
            False,
            "tape_bbo_quorum_incomplete",
        )

    bid = float(mean(float(row.bid) for row in bbo_rows if row.bid is not None))
    ask = float(mean(float(row.ask) for row in bbo_rows if row.ask is not None))
    if bid > ask:
        return TapeMarketProjection(None, False, "tape_composite_book_crossed")
    spread_abs = ask - bid
    mid = (bid + ask) / 2.0
    spread_bps = None if mid <= 0 else spread_abs / mid * 10_000.0

    oldest_received = min(row.received_ts for row in accepted)
    age_ms = max(
        0,
        int((as_of_utc - oldest_received).total_seconds() * 1000),
    )
    quality = (
        QualityState.HEALTHY
        if composite.state is TapeConsensusState.FULL
        else QualityState.DEGRADED
    )
    observation = MarketObservation(
        observation_id=composite.composite_id,
        asset_id=composite.asset_id,
        venue="AETHER_TAPE",
        bid=bid,
        ask=ask,
        last=(
            float(mean(float(row.last) for row in accepted if row.last is not None))
            if all(row.last is not None for row in accepted)
            else None
        ),
        mark=float(composite.composite_mark),
        source=TAPE_MARKET_SOURCE_ID,
        exchange_ts=None,
        received_ts=oldest_received,
        age_ms=age_ms,
        spread_abs=spread_abs,
        spread_bps=spread_bps,
        session_state=calendar.session_state,
        quality_state=quality,
        fallback_reason=(
            None
            if composite.state is TapeConsensusState.FULL
            else f"tape_state:{composite.state.value}"
        ),
        calendar_state=calendar.calendar_state,
        data_version=TAPE_MARKET_DATA_VERSION,
    )
    ready = (
        composite.state is TapeConsensusState.FULL
        and calendar.eligible
    )
    return TapeMarketProjection(
        observation=observation,
        strategy_ready=ready,
        reason="tape_market_ready" if ready else "tape_not_full_or_session_ineligible",
    )



def load_preferred_tape_market_observation(
    conn,
    store,
    *,
    asset_id: str,
    calendar_id: str,
    as_of_utc: datetime,
) -> TapeMarketProjection:
    """Load the latest persisted FULL Tape and project it into the canonical market ledger."""
    composite = store.latest_tape_composite(conn, asset_id=asset_id)
    if composite is None:
        return TapeMarketProjection(None, False, "tape_not_observed")
    source_observations = store.load_tape_source_observations(
        conn,
        observation_ids=composite.source_observation_ids,
    )
    projection = project_tape_market_observation(
        composite,
        source_observations=source_observations,
        calendar=calendar_decision(
            calendar_id=calendar_id,
            at_utc=as_of_utc,
            exception_provider=None,
        ),
        as_of_utc=as_of_utc,
    )
    if not projection.strategy_ready or projection.observation is None:
        return projection

    identity = f"{composite.composite_id}|{as_of_utc.isoformat()}"
    observation_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    observation = replace(
        projection.observation,
        observation_id=observation_id,
        data_version=(
            projection.observation.data_version
            + ":composite="
            + composite.composite_id[:16]
        ),
    )
    existing = store.load_market_observation(
        conn,
        observation_id=observation.observation_id,
    )
    if existing is None:
        store.record_market_observation(conn, observation)
    else:
        observation = existing
    return TapeMarketProjection(
        observation=observation,
        strategy_ready=True,
        reason="tape_market_ready",
    )
