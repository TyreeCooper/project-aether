from app.profitability import ProfitabilityGate, StaticCostModel


def test_cost_model_converts_fees_spread_and_slippage_to_bps():
    model = StaticCostModel(
        taker_fee_rate=0.0026,
        spread_bps=10.0,
        slippage_bps=5.0,
    )
    cost = model.estimate(qty=0.1, reference_price=50_000.0)

    # 26 fee bps + 5 half-spread bps + 5 slippage bps.
    assert round(cost.total_cost_bps, 6) == 36.0
    assert round(cost.total_cost_usd, 2) == 18.0


def test_gate_rejects_edge_that_does_not_clear_cost_multiple():
    gate = ProfitabilityGate(
        StaticCostModel(taker_fee_rate=0.0026, spread_bps=10.0, slippage_bps=5.0),
        minimum_edge_multiple=1.25,
        enforce=True,
    )

    decision = gate.evaluate(
        qty=0.1,
        reference_price=50_000.0,
        expected_move_bps=40.0,
    )

    assert decision.minimum_required_bps == 45.0
    assert decision.allowed is False
    assert decision.reason == "edge_below_cost_threshold"


def test_missing_edge_is_explicit_but_allowed_in_advisory_paper_mode():
    gate = ProfitabilityGate(
        StaticCostModel(taker_fee_rate=0.0026),
        enforce=False,
    )

    decision = gate.evaluate(
        qty=0.01,
        reference_price=50_000.0,
        expected_move_bps=None,
    )

    assert decision.allowed is True
    assert decision.enforced is False
    assert decision.reason == "expected_edge_unavailable"
