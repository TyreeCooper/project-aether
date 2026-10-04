from __future__ import annotations

import pytest

from aether_vnext.market_fabric_event_log import (
    EventKind,
    replay_hash_stream,
)
from aether_vnext.market_fabric_sequencer_ha import (
    FencedLeaderError,
    ReplicatedPartitionLog,
)


def test_takeover_fences_prior_leader_and_preserves_total_order() -> None:
    log = ReplicatedPartitionLog(
        partition_id="btc_usd",
        code_revision="fixture",
    )
    leader_a = log.acquire_initial(leader_id="node-a")
    first = log.append(
        leader_a,
        event_kind=EventKind.PACKET,
        logged_elapsed_ms=100,
        event_id="p1",
        dedupe_key="p1",
        payload={"source": "kraken"},
    )
    assert first is not None
    assert first.log_seq == 1
    assert first.sequencer_epoch == 1

    leader_b = log.takeover(
        new_leader_id="node-b",
        expected_prior_epoch=1,
    )
    assert leader_b.epoch == 2

    with pytest.raises(FencedLeaderError, match="fenced"):
        log.append(
            leader_a,
            event_kind=EventKind.PACKET,
            logged_elapsed_ms=110,
            event_id="stale-writer",
            dedupe_key="stale-writer",
            payload={},
        )

    second = log.append(
        leader_b,
        event_kind=EventKind.TICK,
        logged_elapsed_ms=120,
        event_id="t1",
        dedupe_key="t1",
        payload={},
    )
    assert second is not None
    assert second.log_seq == 2
    assert second.sequencer_epoch == 2


def test_stale_takeover_request_cannot_create_split_brain() -> None:
    log = ReplicatedPartitionLog(
        partition_id="btc_usd",
        code_revision="fixture",
    )
    log.acquire_initial(leader_id="node-a")
    log.takeover(new_leader_id="node-b", expected_prior_epoch=1)

    with pytest.raises(FencedLeaderError, match="stale takeover"):
        log.takeover(new_leader_id="node-c", expected_prior_epoch=1)

    assert log.current_lease is not None
    assert log.current_lease.leader_id == "node-b"
    assert log.current_lease.epoch == 2


def test_crash_after_durable_append_replays_without_duplicate_or_gap() -> None:
    log = ReplicatedPartitionLog(
        partition_id="btc_usd",
        code_revision="fixture",
    )
    leader_a = log.acquire_initial(leader_id="node-a")
    log.append(
        leader_a,
        event_kind=EventKind.PACKET,
        logged_elapsed_ms=100,
        event_id="p1",
        dedupe_key="source:trade-1",
        payload={"source": "kraken"},
    )

    # Simulate crash before any reducer checkpoint. New leader takes over from
    # the durable event list rather than inventing or re-emitting the packet.
    leader_b = log.takeover(new_leader_id="node-b", expected_prior_epoch=1)
    duplicate = log.append(
        leader_b,
        event_kind=EventKind.PACKET,
        logged_elapsed_ms=110,
        event_id="p1-redelivery",
        dedupe_key="source:trade-1",
        payload={"source": "kraken"},
    )
    assert duplicate is None

    log.append(
        leader_b,
        event_kind=EventKind.TICK,
        logged_elapsed_ms=200,
        event_id="t1",
        dedupe_key="t1",
        payload={},
    )

    assert [event.log_seq for event in log.events] == [1, 2]
    first_replay = replay_hash_stream(log.events, checkpoint_every=1)
    second_replay = replay_hash_stream(log.events, checkpoint_every=1)
    assert first_replay == second_replay
