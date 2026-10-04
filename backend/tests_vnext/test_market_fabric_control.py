from __future__ import annotations

import pytest

from aether_vnext.market_fabric_control import (
    ControlActorRole,
    append_halt_event,
    append_route_event,
    replay_control_state,
)
from aether_vnext.market_fabric_event_log import InMemorySequencer
from aether_vnext.market_fabric_identity import RouteAuthorityEvent


def _seq() -> InMemorySequencer:
    return InMemorySequencer(
        partition_id="btc_usd",
        sequencer_epoch=1,
        code_revision="fixture",
    )


def _route() -> RouteAuthorityEvent:
    return RouteAuthorityEvent(
        event_id="route-1",
        route_id="btc-usd-paper",
        instrument_id="btc_usd",
        from_economic_source_id=None,
        to_economic_source_id="kraken_spot",
        initiator="operator",
        reason="MVF route authorization",
        qualification_evidence_refs=("qual:kraken:001",),
        authorization_signature="operator-signature:fixture",
    )


def test_route_and_halt_are_replayable_authority_events() -> None:
    seq = _seq()
    append_route_event(
        seq,
        _route(),
        actor_role=ControlActorRole.OPERATOR,
        logged_elapsed_ms=100,
    )
    state = replay_control_state(seq.events)
    assert state.execution_gate_open is True
    assert state.route_id == "btc-usd-paper"
    assert state.economic_source_id == "kraken_spot"

    append_halt_event(
        seq,
        event_id="halt-1",
        halted=True,
        reason="operator test halt",
        actor_role=ControlActorRole.OPERATOR,
        logged_elapsed_ms=200,
    )
    halted = replay_control_state(seq.events)
    assert halted.execution_gate_open is False
    assert halted.halted is True
    assert halted.halt_reason == "operator test halt"

    append_halt_event(
        seq,
        event_id="halt-2",
        halted=False,
        reason="operator reviewed release",
        actor_role=ControlActorRole.OPERATOR,
        logged_elapsed_ms=300,
    )
    released = replay_control_state(seq.events)
    assert released.execution_gate_open is True
    assert released.halted is False


def test_read_only_projection_cannot_release_or_change_route() -> None:
    seq = _seq()

    with pytest.raises(PermissionError, match="read-only"):
        append_route_event(
            seq,
            _route(),
            actor_role=ControlActorRole.READ_ONLY,
            logged_elapsed_ms=100,
        )

    with pytest.raises(PermissionError, match="read-only"):
        append_halt_event(
            seq,
            event_id="halt-release",
            halted=False,
            reason="forbidden UI release",
            actor_role=ControlActorRole.READ_ONLY,
            logged_elapsed_ms=200,
        )

    assert seq.events == ()


def test_halt_does_not_delete_route_or_market_authority_identity() -> None:
    seq = _seq()
    append_route_event(
        seq,
        _route(),
        actor_role=ControlActorRole.OPERATOR,
        logged_elapsed_ms=100,
    )
    append_halt_event(
        seq,
        event_id="halt-3",
        halted=True,
        reason="risk control",
        actor_role=ControlActorRole.OPERATOR,
        logged_elapsed_ms=110,
    )

    state = replay_control_state(seq.events)
    assert state.halted is True
    assert state.route_id == "btc-usd-paper"
    assert state.economic_source_id == "kraken_spot"
