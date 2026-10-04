from __future__ import annotations

from aether_vnext.market_fabric_liveness import (
    ClockTrust,
    ExecutableBookLiveness,
    ExecutableLivenessState,
    LivenessPolicy,
)


POLICY = LivenessPolicy(
    floor_ms=1000,
    ceiling_ms=10000,
    k_p99=3.0,
    recovery_proofs=3,
    warn_clock_skew_ms=50,
    critical_clock_skew_ms=250,
)


def test_quiet_market_uses_liveness_not_price_change_for_age() -> None:
    state = ExecutableBookLiveness().observe_snapshot(
        elapsed_ms=1000,
        price_or_size_changed=True,
        coherent=True,
        absolute_clock_skew_ms=5,
        policy=POLICY,
    )
    state = state.observe_liveness(
        elapsed_ms=3000,
        absolute_clock_skew_ms=5,
        policy=POLICY,
    )
    checked = state.evaluate_age(
        now_elapsed_ms=5500,
        trailing_p99_liveness_gap_ms=1000,
        policy=POLICY,
    )

    assert checked.state is ExecutableLivenessState.EXECUTABLE
    assert checked.last_update_elapsed_ms == 1000
    assert checked.last_liveness_elapsed_ms == 3000


def test_stopped_liveness_goes_stale_inside_bounded_limit() -> None:
    state = ExecutableBookLiveness().observe_snapshot(
        elapsed_ms=1000,
        price_or_size_changed=True,
        coherent=True,
        absolute_clock_skew_ms=0,
        policy=POLICY,
    )
    checked = state.evaluate_age(
        now_elapsed_ms=5001,
        trailing_p99_liveness_gap_ms=1000,
        policy=POLICY,
    )

    assert POLICY.stale_limit_ms(trailing_p99_liveness_gap_ms=1000) == 3000
    assert checked.state is ExecutableLivenessState.STALE
    assert checked.stale_reason == "LIVENESS_EXPIRED"


def test_stale_recovery_requires_snapshot_and_consecutive_proofs() -> None:
    state = ExecutableBookLiveness().observe_snapshot(
        elapsed_ms=1000,
        price_or_size_changed=True,
        coherent=True,
        absolute_clock_skew_ms=0,
        policy=POLICY,
    ).evaluate_age(
        now_elapsed_ms=5001,
        trailing_p99_liveness_gap_ms=1000,
        policy=POLICY,
    )
    assert state.state is ExecutableLivenessState.STALE

    # Heartbeat alone cannot revive a stale book.
    state = state.observe_liveness(
        elapsed_ms=5100,
        absolute_clock_skew_ms=0,
        policy=POLICY,
    )
    assert state.state is ExecutableLivenessState.STALE
    assert state.consecutive_recovery_proofs == 0

    state = state.observe_snapshot(
        elapsed_ms=5200,
        price_or_size_changed=False,
        coherent=True,
        absolute_clock_skew_ms=0,
        policy=POLICY,
    )
    for elapsed in (5300, 5400):
        state = state.observe_liveness(
            elapsed_ms=elapsed,
            absolute_clock_skew_ms=0,
            policy=POLICY,
        )
        assert state.state is ExecutableLivenessState.STALE

    state = state.observe_liveness(
        elapsed_ms=5500,
        absolute_clock_skew_ms=0,
        policy=POLICY,
    )
    assert state.state is ExecutableLivenessState.EXECUTABLE
    assert state.stale_reason is None


def test_critical_clock_skew_fails_closed() -> None:
    assert POLICY.clock_trust(absolute_skew_ms=50) is ClockTrust.WARN
    assert POLICY.clock_trust(absolute_skew_ms=250) is ClockTrust.UNTRUSTED

    state = ExecutableBookLiveness().observe_snapshot(
        elapsed_ms=1000,
        price_or_size_changed=True,
        coherent=True,
        absolute_clock_skew_ms=250,
        policy=POLICY,
    )
    assert state.state is ExecutableLivenessState.STALE
    assert state.stale_reason == "CLOCK_UNTRUSTED"


def test_adaptive_stale_limit_is_clamped() -> None:
    assert POLICY.stale_limit_ms(trailing_p99_liveness_gap_ms=1) == 1000
    assert POLICY.stale_limit_ms(trailing_p99_liveness_gap_ms=2000) == 6000
    assert POLICY.stale_limit_ms(trailing_p99_liveness_gap_ms=100000) == 10000
