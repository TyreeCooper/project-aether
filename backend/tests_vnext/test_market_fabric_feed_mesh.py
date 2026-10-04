from __future__ import annotations

from aether_vnext.market_fabric_feed_mesh import (
    CircuitState,
    FeedLane,
    LanePolicy,
    LanePriority,
    MarketFabricFeedMesh,
    OverflowAction,
)


def _mesh() -> MarketFabricFeedMesh[str]:
    mesh = MarketFabricFeedMesh[str]()
    mesh.add_lane(
        FeedLane(
            lane_id="exec:kraken",
            policy=LanePolicy(
                capacity=4,
                high_water_mark=3,
                priority=LanePriority.EXECUTABLE,
                overflow_action=OverflowAction.REJECT_NEW,
            ),
        )
    )
    mesh.add_lane(
        FeedLane(
            lane_id="witness:coinbase",
            policy=LanePolicy(
                capacity=2,
                high_water_mark=2,
                priority=LanePriority.WITNESS,
                overflow_action=OverflowAction.SHED_OLDEST,
            ),
        )
    )
    return mesh


def test_witness_overload_is_explicit_and_does_not_stall_executable_lane() -> None:
    mesh = _mesh()

    assert mesh.enqueue("witness:coinbase", "w1")
    assert mesh.enqueue("witness:coinbase", "w2")
    assert mesh.enqueue("witness:coinbase", "w3")

    witness = mesh.lane("witness:coinbase")
    assert witness.depth == 2
    assert witness.telemetry.overflow_events == 1
    assert witness.telemetry.shed_events == 1
    assert witness.fidelity_degraded is True

    assert mesh.enqueue("exec:kraken", "e1")
    executable = mesh.lane("exec:kraken")
    assert executable.depth == 1
    assert executable.circuit_state is CircuitState.CLOSED
    assert executable.fidelity_degraded is False


def test_circuit_breaker_failure_is_local_to_one_lane() -> None:
    mesh = _mesh()
    witness = mesh.lane("witness:coinbase")
    for _ in range(3):
        witness.record_failure()

    assert witness.circuit_state is CircuitState.OPEN
    assert mesh.enqueue("witness:coinbase", "blocked") is False
    assert mesh.enqueue("exec:kraken", "still-moving") is True
    assert mesh.lane("exec:kraken").circuit_state is CircuitState.CLOSED


def test_executable_overflow_rejects_without_silent_loss() -> None:
    mesh = _mesh()
    for index in range(4):
        assert mesh.enqueue("exec:kraken", f"e{index}") is True

    assert mesh.enqueue("exec:kraken", "overflow") is False
    lane = mesh.lane("exec:kraken")
    assert lane.depth == 4
    assert lane.telemetry.overflow_events == 1
    assert lane.telemetry.rejected_events == 1


def test_feed_mesh_snapshot_prioritizes_executable_lane() -> None:
    mesh = _mesh()
    rows = mesh.snapshot()

    assert rows[0]["lane_id"] == "exec:kraken"
    assert rows[0]["priority"] == "EXECUTABLE"
    assert rows[1]["lane_id"] == "witness:coinbase"
