from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aether_vnext.calendars import CalendarDecision
from aether_vnext.domain import CalendarState, QualityState, SessionState
from aether_vnext.tape import (
    TapeCompositeObservation,
    TapeConsensusState,
    TapeSourceObservation,
    TapeSourceQuality,
)
from aether_vnext.tape_market_bridge import project_tape_market_observation


UTC = timezone.utc
NOW = datetime(2026, 10, 3, 17, 45, tzinfo=UTC)


def _calendar() -> CalendarDecision:
    return CalendarDecision(
        calendar_id="crypto_24x7",
        session_state=SessionState.ACTIVE,
        calendar_state=CalendarState.ALWAYS_OPEN,
        eligible=True,
        focus=True,
        reason="24x7",
    )


def _source(source: str, mark: float) -> TapeSourceObservation:
    return TapeSourceObservation(
        observation_id=f"{source}-1",
        asset_id="btc",
        source_id=source,
        venue=source,
        source_symbol="BTC/USD",
        contract_id=None,
        bid=mark - 0.5,
        ask=mark + 0.5,
        last=mark,
        mark=mark,
        exchange_ts=NOW - timedelta(milliseconds=25),
        received_ts=NOW - timedelta(milliseconds=20),
        age_ms=20,
        quality=TapeSourceQuality.HEALTHY,
        source_data_version="v1",
        source_ref=f"{source}:BTC/USD",
    )


def _composite(state: TapeConsensusState, count: int = 3) -> TapeCompositeObservation:
    sources = ("a", "b", "c")[:count]
    return TapeCompositeObservation(
        composite_id=f"cmp-{state.value}-{count}",
        asset_id="btc",
        observed_at_utc=NOW,
        state=state,
        composite_mark=(
            None
            if state in {TapeConsensusState.CONTESTED, TapeConsensusState.NOT_OBSERVED}
            else 100000.0
        ),
        median_mark=(
            None if state is TapeConsensusState.NOT_OBSERVED else 100000.0
        ),
        accepted_source_ids=sources,
        rejected_source_ids=(),
        source_observation_ids=tuple(f"{source}-1" for source in sources),
        source_count=count,
        quorum_required=3,
        max_source_age_ms=20 if count else None,
        agreement_bps=0.1 if count else None,
        provenance_complete=True,
    )


def test_full_tape_projects_healthy_strategy_market_truth() -> None:
    composite = _composite(TapeConsensusState.FULL)
    result = project_tape_market_observation(
        composite,
        source_observations=(
            _source("a", 99999.75),
            _source("b", 100000.00),
            _source("c", 100000.25),
        ),
        calendar=_calendar(),
        as_of_utc=NOW,
    )
    assert result.strategy_ready is True
    assert result.reason == "tape_market_ready"
    assert result.observation is not None
    assert result.observation.quality_state is QualityState.HEALTHY
    assert result.observation.source == "aether_consensus_tape"
    assert result.observation.bid is not None
    assert result.observation.ask is not None


def test_degraded_tape_remains_visible_but_cannot_clear_strategy_market_gate() -> None:
    composite = _composite(TapeConsensusState.DEGRADED, count=2)
    result = project_tape_market_observation(
        composite,
        source_observations=(
            _source("a", 99999.75),
            _source("b", 100000.25),
        ),
        calendar=_calendar(),
        as_of_utc=NOW,
    )
    assert result.strategy_ready is False
    assert result.observation is None
    assert result.reason == "tape_bbo_quorum_incomplete"


def test_contested_tape_never_projects_market_observation() -> None:
    result = project_tape_market_observation(
        _composite(TapeConsensusState.CONTESTED),
        source_observations=(
            _source("a", 99900.0),
            _source("b", 100000.0),
            _source("c", 101000.0),
        ),
        calendar=_calendar(),
        as_of_utc=NOW,
    )
    assert result.strategy_ready is False
    assert result.observation is None
    assert result.reason == "tape_contested"
