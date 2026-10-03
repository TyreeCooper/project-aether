from __future__ import annotations

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from aether_vnext.store import VNextStore
from aether_vnext.tape import (
    TapeConsensusState,
    TapeSourceObservation,
    TapeSourceQuality,
)
from aether_vnext.tape_policy import TapeAssetClass, TapeQuorumPolicy
from aether_vnext.tape_runtime import build_and_persist_tape_cycle


UTC = timezone.utc
NOW = datetime(2026, 10, 3, 18, 10, tzinfo=UTC)
POLICY = TapeQuorumPolicy(
    asset_class=TapeAssetClass.CRYPTO,
    required_quorum=3,
    degraded_quorum=2,
    max_sources=5,
    max_source_age_ms=2_000,
    max_divergence_bps=10.0,
)


def _source(source: str, mark: float, *, age_ms: int = 25) -> TapeSourceObservation:
    received = NOW - timedelta(milliseconds=age_ms)
    return TapeSourceObservation(
        observation_id=f"{source}-{age_ms}",
        asset_id="btc",
        source_id=source,
        venue=source,
        source_symbol="BTC-USD",
        contract_id=None,
        bid=mark - 0.5,
        ask=mark + 0.5,
        last=mark,
        mark=mark,
        exchange_ts=received,
        received_ts=received,
        age_ms=age_ms,
        quality=TapeSourceQuality.HEALTHY,
        source_data_version="v1",
        source_ref=f"{source}:BTC-USD",
    )


def _db():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
    return engine, store


def test_one_source_failure_does_not_poison_three_source_quorum() -> None:
    engine, store = _db()
    with engine.begin() as conn:
        result = build_and_persist_tape_cycle(
            conn,
            store,
            asset_id="btc",
            observations=(
                _source("a", 100000.0),
                _source("b", 100000.2),
                _source("c", 99999.9),
            ),
            source_failures={"d": "TimeoutError:provider timeout"},
            policy=POLICY,
            as_of_utc=NOW,
        )
        persisted = store.latest_tape_composite(conn, asset_id="btc")

    assert result.composite.state is TapeConsensusState.FULL
    assert result.source_count == 3
    assert result.source_failures == {"d": "TimeoutError:provider timeout"}
    assert persisted is not None
    assert persisted.composite_id == result.composite.composite_id


def test_two_surviving_sources_are_degraded_not_invented_full_quorum() -> None:
    engine, store = _db()
    with engine.begin() as conn:
        result = build_and_persist_tape_cycle(
            conn,
            store,
            asset_id="btc",
            observations=(
                _source("a", 100000.0),
                _source("b", 100000.2),
            ),
            source_failures={"c": "HTTPStatusError:503"},
            policy=POLICY,
            as_of_utc=NOW,
        )

    assert result.composite.state is TapeConsensusState.DEGRADED
    assert result.composite.source_count == 2
    assert result.composite.can_authorize_execution is False


def test_divergent_source_is_rejected_without_averaging_it_into_tape() -> None:
    engine, store = _db()
    with engine.begin() as conn:
        result = build_and_persist_tape_cycle(
            conn,
            store,
            asset_id="btc",
            observations=(
                _source("a", 100000.0),
                _source("b", 100000.1),
                _source("c", 100000.2),
                _source("bad", 95000.0),
            ),
            source_failures={},
            policy=POLICY,
            as_of_utc=NOW,
        )

    assert result.composite.state is TapeConsensusState.FULL
    assert result.composite.source_count == 3
    assert "bad" in result.composite.rejected_source_ids
    assert result.composite.composite_mark is not None
    assert result.composite.composite_mark > 99999.0
