"""First-proof harness for the canonical AETHER market-truth core."""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json

from aether_vnext.market_truth_coinbase import CoinbaseWitnessSocketSample, collect_coinbase_witness_sample
from aether_vnext.market_truth_contract import EvidenceState, ExecutionState, ProviderRole
from aether_vnext.market_truth_evidence import build_evidence_snapshot
from aether_vnext.market_truth_fabric import apply_executable_packet, executable_transport_down
from aether_vnext.market_truth_kraken import (
    KrakenExecutableAdapter,
    KrakenExecutableSocketSample,
    collect_kraken_executable_sample,
    replay_kraken_capture,
)
from aether_vnext.market_truth_provider import ProviderCard, ProviderCardRegistry, ProviderFeeSchedule
from aether_vnext.market_truth_route import HumanRouteRegistry, RouteRecord


UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class FirstProofEvidence:
    canonical_instrument_id: str
    route_id: str
    executable_public_socket_observed: bool
    witness_public_socket_observed: bool
    cable_pull_blanked_price: bool
    witness_one_percent_did_not_move_executable: bool
    divergence_state: str
    replay_state_match: bool
    replay_book_match: bool
    live_orders_authorized: bool
    captured_executable_packet_count: int
    captured_witness_packet_count: int

    @property
    def passed(self) -> bool:
        return (
            self.executable_public_socket_observed
            and self.witness_public_socket_observed
            and self.cable_pull_blanked_price
            and self.witness_one_percent_did_not_move_executable
            and self.divergence_state == EvidenceState.DIVERGED.value
            and self.replay_state_match
            and self.replay_book_match
            and self.live_orders_authorized is False
        )

    @property
    def proof_evidence_id(self) -> str:
        payload = asdict(self)
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return f"first-proof:{self.canonical_instrument_id}:{digest[:24]}"


def first_proof_provider_cards() -> ProviderCardRegistry:
    # 26 bps is the already-frozen Kraken PAPER taker fee. It moves from legacy
    # product authority into the executable provider card in the new architecture.
    return ProviderCardRegistry((
        ProviderCard(
            provider_id="kraken",
            role=ProviderRole.BOTH,
            venue="Kraken",
            fee_schedule=ProviderFeeSchedule(
                schedule_id="kraken_spot_taker_v1",
                taker_bps=26.0,
            ),
            entitlement="public_market_data;paper_execution_only;live_not_authorized",
        ),
        ProviderCard(
            provider_id="coinbase",
            role=ProviderRole.OBSERVE,
            venue="Coinbase Exchange",
            fee_schedule=ProviderFeeSchedule(
                schedule_id="observe_only_not_applicable",
            ),
            entitlement="public_market_data_only",
        ),
    ))


def first_proof_route(*, human_set_by: str, set_at_utc: datetime) -> RouteRecord:
    return RouteRecord(
        canonical_instrument_id="btc-usd",
        executable_provider_id="kraken",
        witness_provider_ids=("coinbase",),
        human_set_by=human_set_by,
        human_set_at_utc=set_at_utc,
        route_revision=1,
    )


def evaluate_first_proof(
    *,
    route: RouteRecord,
    providers: ProviderCardRegistry,
    executable_sample: KrakenExecutableSocketSample,
    witness_sample: CoinbaseWitnessSocketSample,
    stale_after_ms: int = 15_000,
    witness_max_age_ms: int = 15_000,
    divergence_bps: float = 25.0,
) -> FirstProofEvidence:
    exec_packet = executable_sample.executable_packet
    baseline = apply_executable_packet(
        route,
        exec_packet,
        providers=providers,
        as_of_utc=exec_packet.receive_time_utc,
        stale_after_ms=stale_after_ms,
    )
    if baseline.state is not ExecutionState.EXECUTABLE:
        raise RuntimeError("first proof requires a fresh executable public socket book")

    down = executable_transport_down(route, providers=providers, reason="proof_cable_pull")
    cable_blank = (
        down.state is ExecutionState.NOT_OBSERVED
        and down.bid is None and down.ask is None and down.last_if_printed is None
    )

    original_exec = (
        baseline.bid,
        baseline.ask,
        baseline.last_if_printed,
        baseline.bid_size,
        baseline.ask_size,
    )
    witness = witness_sample.observation
    moved = replace(
        witness,
        bid=None if witness.bid is None else witness.bid * 1.01,
        ask=None if witness.ask is None else witness.ask * 1.01,
        last_if_printed=(
            None if witness.last_if_printed is None
            else witness.last_if_printed * 1.01
        ),
        receive_time_utc=exec_packet.receive_time_utc,
    )
    divergence = build_evidence_snapshot(
        route,
        baseline,
        (moved,),
        providers=providers,
        as_of_utc=exec_packet.receive_time_utc,
        max_witness_age_ms=witness_max_age_ms,
        divergence_bps=divergence_bps,
    )
    unchanged = original_exec == (
        baseline.bid,
        baseline.ask,
        baseline.last_if_printed,
        baseline.bid_size,
        baseline.ask_size,
    )

    replay_adapter = KrakenExecutableAdapter(
        symbol="BTC/USD",
        canonical_instrument_id=route.canonical_instrument_id,
    )
    replayed = replay_kraken_capture(replay_adapter, executable_sample.captures)
    replay_packet = replayed[-1] if replayed else None
    replay_book = (
        None
        if replay_packet is None
        else apply_executable_packet(
            route,
            replay_packet,
            providers=providers,
            as_of_utc=replay_packet.receive_time_utc,
            stale_after_ms=stale_after_ms,
        )
    )
    replay_state_match = replay_book is not None and replay_book.state is baseline.state
    replay_book_match = replay_book is not None and (
        replay_book.bid,
        replay_book.ask,
        replay_book.last_if_printed,
        replay_book.bid_size,
        replay_book.ask_size,
    ) == original_exec

    return FirstProofEvidence(
        canonical_instrument_id=route.canonical_instrument_id,
        route_id=route.route_id,
        executable_public_socket_observed=bool(executable_sample.captures),
        witness_public_socket_observed=bool(witness_sample.captures),
        cable_pull_blanked_price=cable_blank,
        witness_one_percent_did_not_move_executable=unchanged,
        divergence_state=divergence.state.value,
        replay_state_match=bool(replay_state_match),
        replay_book_match=bool(replay_book_match),
        live_orders_authorized=False,
        captured_executable_packet_count=len(executable_sample.captures),
        captured_witness_packet_count=len(witness_sample.captures),
    )


def bind_first_proof(
    registry: HumanRouteRegistry,
    evidence: FirstProofEvidence,
) -> None:
    if not evidence.passed:
        raise RuntimeError("first proof evidence is not complete")
    if len(registry.routes()) != 1:
        raise RuntimeError("first proof must bind while exactly one executable route exists")
    route = registry.routes()[0]
    if route.route_id != evidence.route_id:
        raise RuntimeError("first proof Route mismatch")
    registry.mark_first_proof_passed(proof_evidence_id=evidence.proof_evidence_id)


async def run_live_first_proof(*, human_set_by: str = "operator") -> FirstProofEvidence:
    """Run the public-socket proof without placing or authorizing any order."""
    route = first_proof_route(
        human_set_by=human_set_by,
        set_at_utc=datetime.now(UTC),
    )
    providers = first_proof_provider_cards()
    executable_sample, witness_sample = await asyncio.gather(
        collect_kraken_executable_sample(route, symbol="BTC/USD", timeout_s=15.0),
        collect_coinbase_witness_sample(
            product_id="BTC-USD",
            canonical_instrument_id="btc-usd",
            timeout_s=15.0,
        ),
    )
    return evaluate_first_proof(
        route=route,
        providers=providers,
        executable_sample=executable_sample,
        witness_sample=witness_sample,
    )
