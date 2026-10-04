from __future__ import annotations

from datetime import datetime, timezone
import json

from aether_vnext.market_truth_coinbase import CapturedWitnessPacket, CoinbaseWitnessSocketSample, CoinbaseWitnessAdapter
from aether_vnext.market_truth_first_proof import evaluate_first_proof, first_proof_provider_cards, first_proof_route
from aether_vnext.market_truth_kraken import CapturedProviderPacket, KrakenExecutableAdapter, KrakenExecutableSocketSample


UTC = timezone.utc
NOW = datetime(2026, 10, 4, 21, 0, tzinfo=UTC)


def _exec_sample() -> KrakenExecutableSocketSample:
    status = json.dumps({"channel":"status","data":[{"system":"online","connection_id":1}]})
    ack = json.dumps({"method":"subscribe","success":True})
    ticker = json.dumps({
        "channel":"ticker",
        "data":[{
            "symbol":"BTC/USD",
            "bid":100.0,
            "ask":101.0,
            "last":100.4,
            "bid_qty":2.0,
            "ask_qty":2.5,
            "timestamp":"2026-10-04T21:00:00Z",
        }],
    })
    captures = (
        CapturedProviderPacket(1,status,NOW),
        CapturedProviderPacket(2,ack,NOW),
        CapturedProviderPacket(3,ticker,NOW),
    )
    packet = KrakenExecutableAdapter(
        symbol="BTC/USD", canonical_instrument_id="btc-usd"
    ).parse(json.loads(ticker), received_at_utc=NOW)
    assert packet is not None
    return KrakenExecutableSocketSample(packet,captures,1)


def _witness_sample() -> CoinbaseWitnessSocketSample:
    raw = json.dumps({
        "type":"ticker",
        "product_id":"BTC-USD",
        "best_bid":"100.01",
        "best_ask":"101.01",
        "price":"100.5",
        "time":"2026-10-04T21:00:00Z",
    })
    observation = CoinbaseWitnessAdapter(
        product_id="BTC-USD", canonical_instrument_id="btc-usd"
    ).parse(json.loads(raw), received_at_utc=NOW)
    assert observation is not None
    return CoinbaseWitnessSocketSample(
        observation,
        (CapturedWitnessPacket(1,raw,NOW),),
    )


def test_first_proof_closes_all_three_required_assertions() -> None:
    route = first_proof_route(human_set_by="operator", set_at_utc=NOW)
    evidence = evaluate_first_proof(
        route=route,
        providers=first_proof_provider_cards(),
        executable_sample=_exec_sample(),
        witness_sample=_witness_sample(),
        stale_after_ms=2000,
        witness_max_age_ms=2000,
        divergence_bps=25.0,
    )
    assert evidence.cable_pull_blanked_price is True
    assert evidence.witness_one_percent_did_not_move_executable is True
    assert evidence.divergence_state == "DIVERGED"
    assert evidence.replay_state_match is True
    assert evidence.replay_book_match is True
    assert evidence.live_orders_authorized is False
    assert evidence.passed is True
    assert evidence.proof_evidence_id.startswith("first-proof:btc-usd:")
