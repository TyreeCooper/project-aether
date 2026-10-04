from __future__ import annotations

from aether_vnext.market_fabric_event_log import (
    EventKind,
    InMemorySequencer,
    packet_dedupe_key,
    replay_hash_stream,
)


def _sequencer() -> InMemorySequencer:
    return InMemorySequencer(
        partition_id="btc_usd",
        sequencer_epoch=1,
        code_revision="test-revision",
    )


def test_sequencer_assigns_total_order_and_logged_ticks_drive_time() -> None:
    seq = _sequencer()
    seq.append(
        event_kind=EventKind.PACKET,
        logged_elapsed_ms=100,
        event_id="packet-1",
        dedupe_key="packet-1",
        payload={"source": "kraken"},
    )
    seq.append(
        event_kind=EventKind.TICK,
        logged_elapsed_ms=200,
        event_id="tick-1",
        dedupe_key="tick-1",
        payload={},
    )
    seq.append(
        event_kind=EventKind.POLICY,
        logged_elapsed_ms=250,
        event_id="policy-1",
        dedupe_key="policy-1",
        payload={"policy_version": "p2"},
        policy_revision="p2",
    )

    assert [event.log_seq for event in seq.events] == [1, 2, 3]
    assert [event.logged_elapsed_ms for event in seq.events] == [100, 200, 250]


def test_reconnect_duplicate_is_admitted_once_independent_of_transport_epoch() -> None:
    seq = _sequencer()
    identity = packet_dedupe_key(
        economic_source_id="kraken_spot",
        native_event_id="trade-123",
        canonical_payload_hash="hash-a",
    )
    first = seq.append(
        event_kind=EventKind.PACKET,
        logged_elapsed_ms=100,
        event_id="local-1",
        dedupe_key=identity,
        payload={"provider_session_epoch": "before-reconnect"},
    )
    duplicate = seq.append(
        event_kind=EventKind.PACKET,
        logged_elapsed_ms=110,
        event_id="local-2",
        dedupe_key=identity,
        payload={"provider_session_epoch": "after-reconnect"},
    )

    assert first is not None
    assert duplicate is None
    assert len(seq.events) == 1
    assert seq.duplicate_count == 1


def test_same_input_replay_twice_has_identical_checkpoint_hashes() -> None:
    seq = _sequencer()
    fixtures = (
        (EventKind.PACKET, 100, "p1", {"source": "kraken"}),
        (EventKind.TICK, 200, "t1", {}),
        (EventKind.ROUTE, 210, "r1", {"route_id": "btc-usd-paper"}),
        (EventKind.HALT, 300, "h1", {"halted": True}),
        (EventKind.HALT, 400, "h2", {"halted": False}),
    )
    for kind, elapsed, event_id, payload in fixtures:
        seq.append(
            event_kind=kind,
            logged_elapsed_ms=elapsed,
            event_id=event_id,
            dedupe_key=event_id,
            payload=payload,
        )

    first = replay_hash_stream(seq.events, checkpoint_every=2)
    second = replay_hash_stream(tuple(seq.events), checkpoint_every=2)

    assert first == second
    assert len(first) == 3


def test_packet_fingerprint_fallback_is_stable_without_native_event_id() -> None:
    first = packet_dedupe_key(
        economic_source_id="coinbase_exchange",
        native_event_id=None,
        canonical_payload_hash="abc123",
    )
    second = packet_dedupe_key(
        economic_source_id="coinbase_exchange",
        native_event_id=None,
        canonical_payload_hash="abc123",
    )
    assert first == second
