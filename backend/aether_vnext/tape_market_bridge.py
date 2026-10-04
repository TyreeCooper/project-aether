"""Evidence-only compatibility bridge for the legacy Consensus Tape.

Market Fabric v3 forbids witness consensus from manufacturing or replacing the
authorized executable-route book. This module therefore evaluates legacy Tape quorum
only as Market Intelligence evidence. It never persists a consensus-derived
MarketObservation into the canonical executable market ledger.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from aether_vnext.calendars import CalendarDecision, calendar_decision
from aether_vnext.domain import MarketObservation
from aether_vnext.tape import (
    TapeCompositeObservation,
    TapeConsensusState,
    TapeSourceObservation,
)


TAPE_MARKET_SOURCE_ID = "aether_market_intelligence_reference"
TAPE_MARKET_DATA_VERSION = "aether_market_intelligence_reference_v3"


@dataclass(frozen=True, slots=True)
class TapeMarketProjection:
    # Compatibility field: consensus evidence is intentionally never projected into
    # an executable MarketObservation under Market Fabric v3.
    observation: MarketObservation | None
    strategy_ready: bool
    reason: str
    evidence_composite_id: str | None = None
    evidence_only: bool = True


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
    """Evaluate legacy Tape quorum as evidence without creating an executable price."""
    if as_of_utc.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")

    if composite.state is TapeConsensusState.NOT_OBSERVED:
        return TapeMarketProjection(
            None,
            False,
            "tape_not_observed",
            evidence_composite_id=composite.composite_id,
        )
    if composite.state is TapeConsensusState.CONTESTED:
        return TapeMarketProjection(
            None,
            False,
            "tape_contested",
            evidence_composite_id=composite.composite_id,
        )

    accepted = _latest_accepted_by_source(composite, source_observations)
    if len(accepted) != composite.source_count:
        return TapeMarketProjection(
            None,
            False,
            "tape_accepted_source_lineage_incomplete",
            evidence_composite_id=composite.composite_id,
        )

    bbo_rows = tuple(
        row for row in accepted
        if row.bid is not None and row.ask is not None
    )
    if len(bbo_rows) < composite.quorum_required:
        return TapeMarketProjection(
            None,
            False,
            "tape_bbo_quorum_incomplete",
            evidence_composite_id=composite.composite_id,
        )

    ready = (
        composite.state is TapeConsensusState.FULL
        and calendar.eligible
    )
    return TapeMarketProjection(
        observation=None,
        strategy_ready=ready,
        reason=(
            "tape_evidence_ready"
            if ready
            else "tape_not_full_or_session_ineligible"
        ),
        evidence_composite_id=composite.composite_id,
        evidence_only=True,
    )


def load_preferred_tape_market_observation(
    conn,
    store,
    *,
    asset_id: str,
    calendar_id: str,
    as_of_utc: datetime,
) -> TapeMarketProjection:
    """Load latest legacy Tape evidence without writing executable market truth."""
    composite = store.latest_tape_composite(conn, asset_id=asset_id)
    if composite is None:
        return TapeMarketProjection(None, False, "tape_not_observed")
    source_observations = store.load_tape_source_observations(
        conn,
        observation_ids=composite.source_observation_ids,
    )
    return project_tape_market_observation(
        composite,
        source_observations=source_observations,
        calendar=calendar_decision(
            calendar_id=calendar_id,
            at_utc=as_of_utc,
            exception_provider=None,
        ),
        as_of_utc=as_of_utc,
    )
