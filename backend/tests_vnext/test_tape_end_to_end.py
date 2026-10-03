from __future__ import annotations

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from app.vnext_tape import build_vnext_tape_snapshot
from aether_vnext.calendars import calendar_decision
from aether_vnext.execution_provider import execution_provider_profile
from aether_vnext.registry import SEED_REGISTRY
from aether_vnext.store import VNextStore
from aether_vnext.tape import TapeConsensusState, TapeSourceObservation, TapeSourceQuality
from aether_vnext.tape_market_bridge import load_preferred_tape_market_observation
from aether_vnext.tape_policy import TapeAssetClass, TapeQuorumPolicy
from aether_vnext.tape_runtime import build_and_persist_tape_cycle


UTC = timezone.utc
NOW = datetime(2026, 10, 3, 18, 30, tzinfo=UTC)
POLICY = TapeQuorumPolicy(
    asset_class=TapeAssetClass.CRYPTO,
    required_quorum=3,
    degraded_quorum=2,
    max_sources=5,
    max_source_age_ms=10_000,
    max_divergence_bps=20.0,
)


def source(source_id: str, mark: float) -> TapeSourceObservation:
    received = NOW - timedelta(milliseconds=40)
    return TapeSourceObservation(
        observation_id=f"{source_id}-obs",
        asset_id="btc",
        source_id=source_id,
        venue=source_id,
        source_symbol="BTCUSD",
        contract_id=None,
        bid=mark - 0.5,
        ask=mark + 0.5,
        last=mark,
        mark=mark,
        exchange_ts=received,
        received_ts=received,
        age_ms=40,
        quality=TapeSourceQuality.HEALTHY,
        source_data_version="v1",
        source_ref=f"{source_id}:BTCUSD",
    )


def test_one_feed_failure_still_reaches_official_tape_api_and_strategy_market_gate() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        cycle = build_and_persist_tape_cycle(
            conn,
            store,
            asset_id="btc",
            observations=(
                source("kraken_public_tape", 100000.0),
                source("coinbase_exchange_tape", 100000.5),
                source("gemini_public_tape", 99999.5),
            ),
            source_failures={"binance_us_tape": "TimeoutError:provider timeout"},
            policy=POLICY,
            as_of_utc=NOW,
        )
        assert cycle.composite.state is TapeConsensusState.FULL
        assert cycle.composite.source_count == 3

        snapshot = build_vnext_tape_snapshot(
            conn,
            store=store,
            as_of_utc=NOW,
        )
        projection = load_preferred_tape_market_observation(
            conn,
            store,
            asset_id="btc",
            calendar_id="crypto_24x7",
            as_of_utc=NOW,
        )

        assert snapshot["paper_only"] is True
        assert snapshot["live_blocked"] is True
        assert snapshot["authority"]["execution_permission"] is False
        assert snapshot["assets"][0]["state"] == "FULL"
        assert snapshot["assets"][0]["source_count"] == 3
        assert projection.strategy_ready is True
        assert projection.observation is not None
        assert projection.observation.source == "aether_consensus_tape"
        persisted = store.load_market_observation(
            conn,
            observation_id=projection.observation.observation_id,
        )
        assert persisted is not None

    btc_execution = execution_provider_profile(SEED_REGISTRY["btc"])
    assert btc_execution.broker == "Kraken"
    assert btc_execution.tape_source_ids == ()


def test_contested_tape_cannot_replace_provider_market_truth() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    store = VNextStore(schema=None)
    with engine.begin() as conn:
        store.create_all_for_test(conn)
        cycle = build_and_persist_tape_cycle(
            conn,
            store,
            asset_id="btc",
            observations=(
                source("a", 100000.0),
                source("b", 102500.0),
                source("c", 97500.0),
            ),
            source_failures={},
            policy=POLICY,
            as_of_utc=NOW,
        )
        assert cycle.composite.state is TapeConsensusState.CONTESTED
        projection = load_preferred_tape_market_observation(
            conn,
            store,
            asset_id="btc",
            calendar_id="crypto_24x7",
            as_of_utc=NOW,
        )
        assert projection.strategy_ready is False
        assert projection.observation is None
        assert projection.reason == "tape_contested"


def test_crypto_calendar_remains_24x7_for_tape_projection() -> None:
    decision = calendar_decision(
        calendar_id="crypto_24x7",
        at_utc=NOW,
        exception_provider=None,
    )
    assert decision.eligible is True
