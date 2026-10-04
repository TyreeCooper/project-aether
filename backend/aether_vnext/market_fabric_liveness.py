"""MF-04 replayable liveness, stale, recovery, and clock-trust contracts.

All age math consumes explicit logged monotonic elapsed time. Reducers never read wall
clock state. Market-change time and application-liveness time are separate.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum


class ExecutableLivenessState(StrEnum):
    NOT_OBSERVED = "NOT_OBSERVED"
    EXECUTABLE = "EXECUTABLE"
    STALE = "STALE"


class ClockTrust(StrEnum):
    TRUSTED = "TRUSTED"
    WARN = "WARN"
    UNTRUSTED = "UNTRUSTED"


@dataclass(frozen=True, slots=True)
class LivenessPolicy:
    floor_ms: int
    ceiling_ms: int
    k_p99: float
    recovery_proofs: int
    warn_clock_skew_ms: int
    critical_clock_skew_ms: int

    def __post_init__(self) -> None:
        if self.floor_ms < 1:
            raise ValueError("floor_ms must be positive")
        if self.ceiling_ms < self.floor_ms:
            raise ValueError("ceiling_ms must be >= floor_ms")
        if self.k_p99 <= 0:
            raise ValueError("k_p99 must be positive")
        if self.recovery_proofs < 1:
            raise ValueError("recovery_proofs must be positive")
        if self.warn_clock_skew_ms < 0:
            raise ValueError("warn_clock_skew_ms cannot be negative")
        if self.critical_clock_skew_ms <= self.warn_clock_skew_ms:
            raise ValueError("critical clock skew must exceed warn skew")

    def stale_limit_ms(self, *, trailing_p99_liveness_gap_ms: int) -> int:
        if trailing_p99_liveness_gap_ms < 0:
            raise ValueError("trailing p99 gap cannot be negative")
        candidate = max(
            float(self.floor_ms),
            self.k_p99 * float(trailing_p99_liveness_gap_ms),
        )
        return int(min(max(candidate, self.floor_ms), self.ceiling_ms))

    def clock_trust(self, *, absolute_skew_ms: int) -> ClockTrust:
        if absolute_skew_ms < 0:
            raise ValueError("absolute_skew_ms cannot be negative")
        if absolute_skew_ms >= self.critical_clock_skew_ms:
            return ClockTrust.UNTRUSTED
        if absolute_skew_ms >= self.warn_clock_skew_ms:
            return ClockTrust.WARN
        return ClockTrust.TRUSTED


@dataclass(frozen=True, slots=True)
class ExecutableBookLiveness:
    state: ExecutableLivenessState = ExecutableLivenessState.NOT_OBSERVED
    last_update_elapsed_ms: int | None = None
    last_liveness_elapsed_ms: int | None = None
    coherent: bool = False
    recovery_snapshot_seen: bool = False
    consecutive_recovery_proofs: int = 0
    stale_reason: str | None = None

    def _validate_elapsed(self, value: int) -> None:
        if value < 0:
            raise ValueError("logged elapsed time cannot be negative")
        prior = self.last_liveness_elapsed_ms
        if prior is not None and value < prior:
            raise ValueError("logged elapsed time cannot move backwards")

    def observe_snapshot(
        self,
        *,
        elapsed_ms: int,
        price_or_size_changed: bool,
        coherent: bool,
        absolute_clock_skew_ms: int,
        policy: LivenessPolicy,
    ) -> "ExecutableBookLiveness":
        self._validate_elapsed(elapsed_ms)
        trust = policy.clock_trust(absolute_skew_ms=absolute_clock_skew_ms)
        if not coherent:
            return replace(
                self,
                state=ExecutableLivenessState.STALE,
                last_liveness_elapsed_ms=elapsed_ms,
                coherent=False,
                recovery_snapshot_seen=False,
                consecutive_recovery_proofs=0,
                stale_reason="BOOK_INCOHERENT",
            )
        if trust is ClockTrust.UNTRUSTED:
            return replace(
                self,
                state=ExecutableLivenessState.STALE,
                last_liveness_elapsed_ms=elapsed_ms,
                coherent=True,
                recovery_snapshot_seen=True,
                consecutive_recovery_proofs=0,
                stale_reason="CLOCK_UNTRUSTED",
            )

        last_update = (
            elapsed_ms
            if price_or_size_changed or self.last_update_elapsed_ms is None
            else self.last_update_elapsed_ms
        )
        if self.state is not ExecutableLivenessState.STALE:
            return replace(
                self,
                state=ExecutableLivenessState.EXECUTABLE,
                last_update_elapsed_ms=last_update,
                last_liveness_elapsed_ms=elapsed_ms,
                coherent=True,
                recovery_snapshot_seen=True,
                consecutive_recovery_proofs=policy.recovery_proofs,
                stale_reason=None,
            )
        return replace(
            self,
            last_update_elapsed_ms=last_update,
            last_liveness_elapsed_ms=elapsed_ms,
            coherent=True,
            recovery_snapshot_seen=True,
            consecutive_recovery_proofs=0,
            stale_reason=self.stale_reason,
        )

    def observe_liveness(
        self,
        *,
        elapsed_ms: int,
        absolute_clock_skew_ms: int,
        policy: LivenessPolicy,
    ) -> "ExecutableBookLiveness":
        self._validate_elapsed(elapsed_ms)
        trust = policy.clock_trust(absolute_skew_ms=absolute_clock_skew_ms)
        if trust is ClockTrust.UNTRUSTED:
            return replace(
                self,
                state=ExecutableLivenessState.STALE,
                last_liveness_elapsed_ms=elapsed_ms,
                consecutive_recovery_proofs=0,
                stale_reason="CLOCK_UNTRUSTED",
            )

        if self.state is ExecutableLivenessState.STALE:
            proofs = (
                self.consecutive_recovery_proofs + 1
                if self.recovery_snapshot_seen and self.coherent
                else 0
            )
            recovered = proofs >= policy.recovery_proofs
            return replace(
                self,
                state=(
                    ExecutableLivenessState.EXECUTABLE
                    if recovered
                    else ExecutableLivenessState.STALE
                ),
                last_liveness_elapsed_ms=elapsed_ms,
                consecutive_recovery_proofs=proofs,
                stale_reason=None if recovered else self.stale_reason,
            )

        return replace(
            self,
            last_liveness_elapsed_ms=elapsed_ms,
            stale_reason=None,
        )

    def evaluate_age(
        self,
        *,
        now_elapsed_ms: int,
        trailing_p99_liveness_gap_ms: int,
        policy: LivenessPolicy,
    ) -> "ExecutableBookLiveness":
        if now_elapsed_ms < 0:
            raise ValueError("now_elapsed_ms cannot be negative")
        if self.last_liveness_elapsed_ms is None:
            return replace(
                self,
                state=ExecutableLivenessState.NOT_OBSERVED,
                stale_reason="NO_LIVENESS_OBSERVED",
            )
        if now_elapsed_ms < self.last_liveness_elapsed_ms:
            raise ValueError("now_elapsed_ms cannot precede last liveness")
        age_ms = now_elapsed_ms - self.last_liveness_elapsed_ms
        limit_ms = policy.stale_limit_ms(
            trailing_p99_liveness_gap_ms=trailing_p99_liveness_gap_ms
        )
        if age_ms > limit_ms:
            return replace(
                self,
                state=ExecutableLivenessState.STALE,
                recovery_snapshot_seen=False,
                consecutive_recovery_proofs=0,
                stale_reason="LIVENESS_EXPIRED",
            )
        return self
