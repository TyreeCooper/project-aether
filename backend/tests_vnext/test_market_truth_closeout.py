from __future__ import annotations

from aether_vnext.market_truth_closeout import evaluate_market_truth_closeout


def test_closeout_requires_canonical_runtime_and_legacy_quarantine() -> None:
    result = evaluate_market_truth_closeout(
        {
            "architecture": "AETHER_MARKET_TRUTH_V1",
            "paper_only": True,
            "live_blocked": True,
            "authority": {
                "witness_can_replace_executable_price": False,
                "automatic_execution_venue_switch_allowed": False,
            },
            "routes": [{"route_id": "route:btc"}],
            "first_proof": {"passed": False},
            "runtime": {"running": True},
        },
        legacy_statuses={
            "ingress": {"enabled": False, "running": False},
            "tape": {"enabled": False, "running": False},
            "strategy": {"enabled": False, "running": False},
        },
    )
    assert result.deployment_ready is True
    assert result.first_proof_complete is False
    assert result.route_count == 1
    assert result.legacy_authority_quarantined is True


def test_closeout_blocks_legacy_authority_or_second_route_before_proof() -> None:
    result = evaluate_market_truth_closeout(
        {
            "architecture": "AETHER_MARKET_TRUTH_V1",
            "paper_only": True,
            "live_blocked": True,
            "authority": {
                "witness_can_replace_executable_price": False,
                "automatic_execution_venue_switch_allowed": False,
            },
            "routes": [{"route_id": "a"}, {"route_id": "b"}],
            "first_proof": {"passed": False},
            "runtime": {"running": True},
        },
        legacy_statuses={
            "ingress": {"enabled": True, "running": True},
            "tape": {"enabled": False, "running": False},
            "strategy": {"enabled": False, "running": False},
        },
    )
    assert result.deployment_ready is False
    assert "first_proof_route_limit_violated" in result.blockers
    assert "legacy_ingress_authority_not_quarantined" in result.blockers
