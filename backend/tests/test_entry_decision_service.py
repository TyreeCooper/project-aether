from app.profitability import ProfitabilityGate, StaticCostModel
from app.services import EntryDecisionService


def _service(*, enforce: bool = False) -> EntryDecisionService:
    gate = ProfitabilityGate(
        StaticCostModel(taker_fee_rate=0.001),
        minimum_edge_multiple=1.0,
        enforce=enforce,
    )
    return EntryDecisionService(gate)


def _base(service: EntryDecisionService, **kwargs):
    data = dict(
        expected_move_bps=None,
        reference_price=50_000.0,
        qty=0.01,
        flatten_lock=False,
        paper_mode=True,
        live_blocked=True,
        position_btc=0.0,
        max_position_btc=0.02,
        equity=10_000.0,
        peak_equity=10_000.0,
        max_drawdown_pct=8.0,
        daily_realized=0.0,
        daily_loss_cap=250.0,
    )
    data.update(kwargs)
    return service.evaluate(**data)


def test_service_runs_profitability_then_risk():
    result = _base(_service(), flatten_lock=True)

    assert result.allowed is False
    assert result.reason == "flatten_lock"
    assert result.profitability.reason == "expected_edge_unavailable"


def test_enforced_profitability_can_block_before_risk():
    result = _base(
        _service(enforce=True),
        expected_move_bps=5.0,
        flatten_lock=True,
    )

    assert result.allowed is False
    assert result.reason == "edge_below_cost_threshold"
