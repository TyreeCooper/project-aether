from __future__ import annotations

from aether_vnext.market_fabric_paper_fill import (
    DepthLevel,
    PaperFidelity,
    PaperFillPolicy,
    simulate_paper_fill,
)


POLICY = PaperFillPolicy(
    policy_version="paper-fixture-v1",
    modeled_latency_ms=150,
    fee_bps=5.0,
    max_participation=0.5,
    l1_quantity_cap=2.0,
    reject_on_insufficient_depth=True,
)


def test_l2_buy_walks_only_authorized_executable_asks() -> None:
    result = simulate_paper_fill(
        side="BUY",
        quantity=2.0,
        bid_levels=(DepthLevel(99.0, 10.0),),
        ask_levels=(
            DepthLevel(100.0, 2.0),
            DepthLevel(101.0, 4.0),
        ),
        policy=POLICY,
        l2_available=True,
    )

    assert result.accepted is True
    assert result.fidelity is PaperFidelity.L2_WALK
    # 50% participation: 1 @ 100, then 1 @ 101.
    assert result.average_price == 100.5
    assert result.filled_quantity == 2.0
    assert result.live_execution_authorized is False


def test_insufficient_l2_depth_rejects_instead_of_inventing_liquidity() -> None:
    result = simulate_paper_fill(
        side="BUY",
        quantity=10.0,
        bid_levels=(),
        ask_levels=(DepthLevel(100.0, 2.0),),
        policy=POLICY,
        l2_available=True,
    )

    assert result.accepted is False
    assert result.rejection_reason == "INSUFFICIENT_DISPLAYED_DEPTH"
    assert result.average_price is None


def test_l1_mode_is_explicitly_capped() -> None:
    result = simulate_paper_fill(
        side="SELL",
        quantity=3.0,
        bid_levels=(DepthLevel(99.0, 10.0),),
        ask_levels=(DepthLevel(100.0, 10.0),),
        policy=POLICY,
        l2_available=False,
    )

    assert result.accepted is False
    assert result.fidelity is PaperFidelity.L1_CAPPED
    assert result.rejection_reason == "L1_QUANTITY_CAP_EXCEEDED"


def test_no_executable_depth_means_no_paper_fill() -> None:
    result = simulate_paper_fill(
        side="BUY",
        quantity=1.0,
        bid_levels=(),
        ask_levels=(),
        policy=POLICY,
        l2_available=False,
    )

    assert result.accepted is False
    assert result.fidelity is PaperFidelity.NONE
    assert result.rejection_reason == "EXECUTABLE_DEPTH_NOT_OBSERVED"
