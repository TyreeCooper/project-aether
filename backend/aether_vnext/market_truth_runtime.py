"""Canonical five-layer market-truth runtime for the first AETHER proof.

Only BTC/USD is routed. Kraken public WebSocket v2 is the executable transport and
Coinbase Exchange public WebSocket is an observe-only witness. Transport failures
never change the human Route and never substitute witness prices.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from typing import Any

import websockets

from aether_vnext.freeze import LIVE_BLOCKED, PAPER_ONLY
from aether_vnext.kraken_catalog import fetch_kraken_spot_pair_facts
from aether_vnext.market_truth_coinbase import (
    COINBASE_WITNESS_WS_URL,
    CoinbaseWitnessAdapter,
)
from aether_vnext.market_truth_contract import EvidenceState, ExecutionState
from aether_vnext.market_truth_evidence import EvidenceSnapshot, build_evidence_snapshot
from aether_vnext.market_truth_fabric import (
    ExecutableBookSnapshot,
    apply_executable_packet,
    executable_transport_down,
    refresh_executable_state,
)
from aether_vnext.market_truth_first_proof import (
    first_proof_provider_cards,
    first_proof_route,
)
from aether_vnext.market_truth_kraken import (
    KRAKEN_EXECUTABLE_WS_V2_URL,
    KrakenExecutableAdapter,
)
from aether_vnext.market_truth_provider import ProviderCardRegistry
from aether_vnext.market_truth_route import HumanRouteRegistry, RouteRecord
from aether_vnext.market_truth_universe import AssetUniverse, AssetUniverseRow


UTC = timezone.utc


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat()


def _evidence_none(route: RouteRecord) -> EvidenceSnapshot:
    return EvidenceSnapshot(
        canonical_instrument_id=route.canonical_instrument_id,
        route_id=route.route_id,
        state=EvidenceState.NO_WITNESS,
        configured_witness_count=len(route.witness_provider_ids),
        observed_witness_count=0,
        fresh_coherent_witness_count=0,
        assessments=(),
        max_gap_bps_to_executable=None,
    )


def _serialize_provider_cards(registry: ProviderCardRegistry) -> list[dict[str, object]]:
    rows = []
    for card in registry.cards():
        rows.append({
            "provider_id": card.provider_id,
            "role": card.role.value,
            "venue": card.venue,
            "entitlement": card.entitlement,
            "fee_schedule": asdict(card.fee_schedule),
        })
    return rows


def build_market_truth_snapshot(
    *,
    universe: AssetUniverse | None,
    providers: ProviderCardRegistry,
    route: RouteRecord | None,
    book: ExecutableBookSnapshot | None,
    evidence: EvidenceSnapshot | None,
    runtime_status: dict[str, object],
    proof_evidence_id: str | None = None,
) -> dict[str, object]:
    universe_rows = [] if universe is None else [
        asdict(row) for row in universe.rows()
    ]
    routes = [] if route is None else [{
        "route_id": route.route_id,
        "canonical_instrument_id": route.canonical_instrument_id,
        "executable_provider_id": route.executable_provider_id,
        "witness_provider_ids": list(route.witness_provider_ids),
        "human_set_by": route.human_set_by,
        "human_set_at_utc": _iso(route.human_set_at_utc),
        "route_revision": route.route_revision,
        "automatic_execution_venue_switch_allowed": False,
    }]

    instruments: list[dict[str, object]] = []
    if route is not None:
        row = None if universe is None else universe.get(route.canonical_instrument_id)
        executable = book
        witness = evidence or _evidence_none(route)
        instruments.append({
            "asset_id": route.canonical_instrument_id,
            "symbol": "BTC/USD" if route.canonical_instrument_id == "btc-usd" else route.canonical_instrument_id,
            "execution_symbol": "BTC/USD" if route.canonical_instrument_id == "btc-usd" else None,
            "asset_class": None if row is None else row.asset_class,
            "commissioned": True,
            "executable": {
                "state": (
                    ExecutionState.NOT_OBSERVED.value
                    if executable is None else executable.state.value
                ),
                "provider_id": route.executable_provider_id,
                "venue": (
                    providers.require(route.executable_provider_id).venue
                    if executable is None else executable.venue
                ),
                "transport_id": None if executable is None else executable.transport_id,
                "bid": None if executable is None else executable.bid,
                "ask": None if executable is None else executable.ask,
                "last_if_printed": None if executable is None else executable.last_if_printed,
                "last": None if executable is None else executable.last_if_printed,
                "bid_size": None if executable is None else executable.bid_size,
                "ask_size": None if executable is None else executable.ask_size,
                "venue_time_utc": None if executable is None else _iso(executable.venue_time_utc),
                "received_ts_utc": None if executable is None else _iso(executable.receive_time_utc),
                "reference_ts_utc": (
                    None
                    if executable is None
                    else _iso(executable.venue_time_utc or executable.receive_time_utc)
                ),
                "reason": "runtime_not_ready" if executable is None else executable.state_reason,
            },
            "intelligence": {
                "evidence_state": witness.state.value,
                "authority": witness.authority,
                "configured_witness_count": witness.configured_witness_count,
                "observed_witness_count": witness.observed_witness_count,
                "fresh_coherent_witness_count": witness.fresh_coherent_witness_count,
                "max_gap_bps_to_executable": witness.max_gap_bps_to_executable,
                "derived_reference_executable": False,
            },
        })

    quoted = sum(
        1 for row in instruments
        if (row.get("executable") or {}).get("state") == ExecutionState.EXECUTABLE.value
    )
    evidence_observed = sum(
        1 for row in instruments
        if (row.get("intelligence") or {}).get("evidence_state") != EvidenceState.NO_WITNESS.value
    )
    return {
        "architecture": "AETHER_MARKET_TRUTH_V1",
        "as_of_utc": datetime.now(UTC).isoformat(),
        "paper_only": bool(PAPER_ONLY),
        "live_blocked": bool(LIVE_BLOCKED),
        "authority": {
            "execution_price_source": "HUMAN_ROUTE_EXECUTABLE_PROVIDER_ONLY",
            "witness_can_replace_executable_price": False,
            "automatic_execution_venue_switch_allowed": False,
            "derived_figures_authority": "NON_EXECUTABLE",
        },
        "layers": {
            "asset_universe": "READY" if universe_rows else "WARMING",
            "provider_card": "READY" if providers.cards() else "WARMING",
            "route": "READY" if route is not None else "WARMING",
            "market_fabric": (
                "WARMING" if book is None else book.state.value
            ),
            "execution": "PROOF_LOCKED" if proof_evidence_id is None else "PAPER_READY",
        },
        "asset_universe": universe_rows,
        "provider_cards": _serialize_provider_cards(providers),
        "routes": routes,
        "execution_universe": {
            "asset_universe_count": len(universe_rows),
            "commissioned_count": len(routes),
            "quoted_count": quoted,
            "evidence_observed_count": evidence_observed,
            "ranking_is_allowlist": False,
            "second_route_allowed": proof_evidence_id is not None,
        },
        "instruments": instruments,
        "first_proof": {
            "required": True,
            "passed": proof_evidence_id is not None,
            "proof_evidence_id": proof_evidence_id,
            "maximum_executable_routes_before_pass": 1,
        },
        "runtime": runtime_status,
        "runtime_contract": {
            "executable_domain": "human_route_public_socket",
            "intelligence_domain": "route_named_public_witness_socket",
            "missing_field_semantics": "NULL_NEVER_ZERO",
            "execution_states": ["EXECUTABLE", "STALE", "NOT_OBSERVED"],
            "evidence_states": [
                "NO_WITNESS", "CONTESTED", "DIVERGED",
                "SINGLE_SOURCE", "DEGRADED", "FULL",
            ],
        },
    }


class MarketTruthRuntime:
    def __init__(self) -> None:
        self._stop = asyncio.Event()
        self._ready = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []
        self.universe: AssetUniverse | None = None
        self.providers = first_proof_provider_cards()
        self.route_registry: HumanRouteRegistry | None = None
        self.route: RouteRecord | None = None
        self.book: ExecutableBookSnapshot | None = None
        self.evidence: EvidenceSnapshot | None = None
        self.latest_witness = None
        self.started_at_utc: datetime | None = None
        self.last_progress_at_utc: datetime | None = None
        self.bootstrap_error: str | None = None
        self.executable_error: str | None = None
        self.witness_error: str | None = None
        self.executable_connected = False
        self.witness_connected = False
        self.executable_packet_count = 0
        self.witness_packet_count = 0
        self.proof_evidence_id = (
            os.getenv("AETHER_MARKET_TRUTH_FIRST_PROOF_ID", "").strip() or None
        )

    @property
    def running(self) -> bool:
        return any(not task.done() for task in self._tasks)

    def _progress(self) -> None:
        self.last_progress_at_utc = datetime.now(UTC)

    async def start(self) -> None:
        if self.running:
            return
        if not PAPER_ONLY or not LIVE_BLOCKED:
            raise RuntimeError("canonical market truth requires PAPER_ONLY/LIVE_BLOCKED")
        self._stop.clear()
        self.started_at_utc = datetime.now(UTC)
        self._tasks = [
            asyncio.create_task(self._bootstrap_loop(), name="market-truth-bootstrap"),
            asyncio.create_task(self._executable_loop(), name="market-truth-kraken"),
            asyncio.create_task(self._witness_loop(), name="market-truth-coinbase"),
            asyncio.create_task(self._monitor_loop(), name="market-truth-monitor"),
        ]

    async def stop(self) -> None:
        self._stop.set()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        self.executable_connected = False
        self.witness_connected = False
        if self.route is not None:
            self.book = executable_transport_down(
                self.route, providers=self.providers, reason="runtime_stopped"
            )
        self._progress()

    async def _bootstrap_loop(self) -> None:
        while not self._stop.is_set() and not self._ready.is_set():
            try:
                facts = await asyncio.wait_for(
                    fetch_kraken_spot_pair_facts(canonical_symbols=("BTC/USD",)),
                    timeout=12.0,
                )
                btc = facts.get("BTC/USD")
                if btc is None:
                    raise RuntimeError("BTC/USD missing from Kraken AssetPairs")
                tick_size = btc.get("tick_size")
                quantity_step = btc.get("quantity_step")
                if tick_size is None or quantity_step is None:
                    raise RuntimeError("BTC/USD tick/lot facts not observed")
                universe = AssetUniverse((
                    AssetUniverseRow(
                        canonical_instrument_id="btc-usd",
                        asset_class="spot_crypto",
                        tick_size=float(tick_size),
                        lot_size=float(quantity_step),
                        session_calendar="crypto_24x7",
                    ),
                ))
                route = first_proof_route(
                    human_set_by="repository-owner-approved-preload",
                    set_at_utc=datetime.now(UTC),
                )
                registry = HumanRouteRegistry(
                    universe=universe,
                    providers=self.providers,
                )
                registry.add_human_route(route)
                if self.proof_evidence_id is not None:
                    registry.mark_first_proof_passed(
                        proof_evidence_id=self.proof_evidence_id
                    )
                self.universe = universe
                self.route_registry = registry
                self.route = route
                self.book = executable_transport_down(
                    route, providers=self.providers, reason="awaiting_executable_socket"
                )
                self.evidence = _evidence_none(route)
                self.bootstrap_error = None
                self._ready.set()
                self._progress()
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.bootstrap_error = f"{type(exc).__name__}:{exc}"
                self._progress()
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=5.0)
                except TimeoutError:
                    continue

    async def _executable_loop(self) -> None:
        await self._ready.wait()
        assert self.route is not None
        adapter = KrakenExecutableAdapter(
            symbol="BTC/USD",
            canonical_instrument_id=self.route.canonical_instrument_id,
        )
        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    KRAKEN_EXECUTABLE_WS_V2_URL,
                    ping_interval=20, ping_timeout=20, close_timeout=5,
                ) as socket:
                    await socket.send(json.dumps(
                        adapter.subscription_payload(),
                        sort_keys=True, separators=(",", ":"),
                    ))
                    online = False
                    subscribed = False
                    self.executable_connected = True
                    self.executable_error = None
                    self._progress()
                    while not self._stop.is_set():
                        raw = await socket.recv()
                        received = datetime.now(UTC)
                        payload = json.loads(
                            raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
                        )
                        if isinstance(payload, dict) and payload.get("channel") == "status":
                            rows = payload.get("data") or []
                            if rows and isinstance(rows[0], dict):
                                online = str(rows[0].get("system") or "").lower() == "online"
                                if not online:
                                    raise RuntimeError("Kraken executable venue not online")
                            continue
                        if isinstance(payload, dict) and payload.get("method") == "subscribe":
                            if payload.get("success") is False:
                                raise RuntimeError(
                                    f"Kraken subscription rejected:{payload.get('error')}"
                                )
                            if payload.get("success") is True:
                                subscribed = True
                            continue
                        packet = adapter.parse(payload, received_at_utc=received)
                        if packet is None or not online or not subscribed:
                            continue
                        self.book = apply_executable_packet(
                            self.route,
                            packet,
                            providers=self.providers,
                            as_of_utc=received,
                            stale_after_ms=5_000,
                        )
                        self.executable_packet_count += 1
                        self._progress()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.executable_error = f"{type(exc).__name__}:{exc}"
            finally:
                self.executable_connected = False
                if self.route is not None:
                    self.book = executable_transport_down(
                        self.route,
                        providers=self.providers,
                        reason="executable_socket_down",
                    )
                self._progress()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=1.0)
            except TimeoutError:
                continue

    async def _witness_loop(self) -> None:
        await self._ready.wait()
        assert self.route is not None
        adapter = CoinbaseWitnessAdapter(
            product_id="BTC-USD",
            canonical_instrument_id=self.route.canonical_instrument_id,
        )
        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    COINBASE_WITNESS_WS_URL,
                    ping_interval=20, ping_timeout=20, close_timeout=5,
                ) as socket:
                    await socket.send(json.dumps(
                        adapter.subscription_payload(),
                        sort_keys=True, separators=(",", ":"),
                    ))
                    self.witness_connected = True
                    self.witness_error = None
                    self._progress()
                    while not self._stop.is_set():
                        raw = await socket.recv()
                        received = datetime.now(UTC)
                        payload = json.loads(
                            raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
                        )
                        if isinstance(payload, dict) and payload.get("type") == "error":
                            raise RuntimeError(
                                f"Coinbase witness subscription error:{payload.get('message')}"
                            )
                        observation = adapter.parse(payload, received_at_utc=received)
                        if observation is None:
                            continue
                        self.latest_witness = observation
                        self.witness_packet_count += 1
                        self._progress()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.witness_error = f"{type(exc).__name__}:{exc}"
            finally:
                self.witness_connected = False
                self.latest_witness = None
                self._progress()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=1.0)
            except TimeoutError:
                continue

    async def _monitor_loop(self) -> None:
        await self._ready.wait()
        while not self._stop.is_set():
            now = datetime.now(UTC)
            if self.book is not None:
                self.book = refresh_executable_state(
                    self.book,
                    as_of_utc=now,
                    stale_after_ms=5_000,
                )
            if self.route is not None and self.book is not None:
                witnesses = (
                    () if self.latest_witness is None else (self.latest_witness,)
                )
                self.evidence = build_evidence_snapshot(
                    self.route,
                    self.book,
                    witnesses,
                    providers=self.providers,
                    as_of_utc=now,
                    max_witness_age_ms=5_000,
                    divergence_bps=25.0,
                )
            self._progress()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=0.5)
            except TimeoutError:
                continue

    def status_payload(self) -> dict[str, object]:
        return {
            "running": self.running,
            "started_at_utc": _iso(self.started_at_utc),
            "last_progress_at_utc": _iso(self.last_progress_at_utc),
            "bootstrap_ready": self._ready.is_set(),
            "bootstrap_error": self.bootstrap_error,
            "executable_connected": self.executable_connected,
            "executable_error": self.executable_error,
            "executable_packet_count": self.executable_packet_count,
            "witness_connected": self.witness_connected,
            "witness_error": self.witness_error,
            "witness_packet_count": self.witness_packet_count,
        }

    def snapshot(self) -> dict[str, object]:
        return build_market_truth_snapshot(
            universe=self.universe,
            providers=self.providers,
            route=self.route,
            book=self.book,
            evidence=self.evidence,
            runtime_status=self.status_payload(),
            proof_evidence_id=self.proof_evidence_id,
        )


_runtime: MarketTruthRuntime | None = None


def configured_market_truth_runtime() -> MarketTruthRuntime:
    global _runtime
    if _runtime is None:
        _runtime = MarketTruthRuntime()
    return _runtime


async def start_configured_market_truth_runtime() -> None:
    await configured_market_truth_runtime().start()


async def stop_configured_market_truth_runtime() -> None:
    if _runtime is not None:
        await _runtime.stop()


def configured_market_truth_snapshot() -> dict[str, object]:
    return configured_market_truth_runtime().snapshot()
