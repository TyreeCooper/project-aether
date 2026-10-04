from __future__ import annotations

from aether_vnext.market_fabric_event_log import EventKind, InMemorySequencer
from aether_vnext.market_fabric_history import (
    AppendOnlyMarketHistory,
    build_checkpoint,
    reconstruct_trade_evidence,
    verify_restore,
)


def _fixture():
    seq = InMemorySequencer(
        partition_id="btc_usd",
        sequencer_epoch=1,
        code_revision="rev-a",
    )
    for kind, elapsed, event_id, payload in (
        (EventKind.PACKET, 100, "p1", {"source": "kraken"}),
        (EventKind.TICK, 200, "t1", {}),
        (EventKind.ROUTE, 250, "r1", {"route_id": "btc-paper"}),
    ):
        seq.append(
            event_kind=kind,
            logged_elapsed_ms=elapsed,
            event_id=event_id,
            dedupe_key=event_id,
            payload=payload,
        )
    history = AppendOnlyMarketHistory()
    records = tuple(history.record_ordered_event(event) for event in seq.events)
    return seq.events, records


def test_restore_reproduces_state_hash_and_manifest_hash() -> None:
    events, records = _fixture()
    checkpoint = build_checkpoint(events=events, records=records)

    passed, errors = verify_restore(
        checkpoint=checkpoint,
        restored_events=events,
        restored_records=records,
    )

    assert passed is True
    assert errors == ()


def test_restore_detects_missing_history_record() -> None:
    events, records = _fixture()
    checkpoint = build_checkpoint(events=events, records=records)

    passed, errors = verify_restore(
        checkpoint=checkpoint,
        restored_events=events,
        restored_records=records[:-1],
    )

    assert passed is False
    assert "history_record_count_mismatch" in errors


def test_append_only_history_rejects_conflicting_rewrite() -> None:
    events, records = _fixture()
    history = AppendOnlyMarketHistory()
    history.append(records[0])

    conflicting = type(records[0])(
        record_id=records[0].record_id,
        partition_id=records[0].partition_id,
        log_seq=records[0].log_seq,
        event_id="different-event",
        raw_payload_ref=None,
        raw_payload_hash=None,
        code_revision=records[0].code_revision,
        policy_revision=None,
        reference_revision=None,
    )

    try:
        history.append(conflicting)
    except ValueError as exc:
        assert "conflicting immutable" in str(exc)
    else:
        raise AssertionError("conflicting history rewrite should fail")


def test_trade_reconstruction_is_explicitly_incomplete_when_evidence_missing() -> None:
    events, records = _fixture()
    available = {record.record_id: record for record in records[:-1]}
    source_ids = tuple(record.record_id for record in records)

    result = reconstruct_trade_evidence(
        decision_ref="decision-1",
        execution_ref="paper-fill-1",
        source_record_ids=source_ids,
        available_records=available,
    )

    assert result["complete"] is False
    assert result["missing_record_ids"] == [records[-1].record_id]
