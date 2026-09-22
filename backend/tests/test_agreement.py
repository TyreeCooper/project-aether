from app.agreement import strategy_agreement


CONFIG = {"short_ma": 8, "long_ma": 21}


def _held(passed=True):
    return {"ok": True, "profitability_gate_pass": passed, "config": CONFIG}


def _forward(profit=True, sample_defined=True, sample=True):
    return {
        "ok": True,
        "profitability_gate_pass": profit,
        "sample_gate_defined": sample_defined,
        "sample_gate_pass": sample,
        "forward_gate_pass": profit and sample_defined and sample,
    }


def test_agreement_requires_both_independent_evidence_gates():
    out = strategy_agreement(_held(), _forward())
    assert out["agreement"] is True
    assert out["champion_candidate"] == CONFIG
    assert out["live_trading"] is False


def test_agreement_fails_when_held_out_gate_fails():
    out = strategy_agreement(_held(False), _forward())
    assert out["agreement"] is False
    assert out["champion_candidate"] is None
    assert "held_out_profitability_gate" in out["blockers"]


def test_agreement_fails_without_defined_meaningful_forward_sample():
    out = strategy_agreement(_held(), _forward(sample_defined=False, sample=False))
    assert out["agreement"] is False
    assert out["champion_candidate"] is None
    assert "forward_meaningful_sample_threshold" in out["blockers"]


def test_agreement_fails_when_forward_profitability_fails():
    out = strategy_agreement(_held(), _forward(profit=False))
    assert out["agreement"] is False
    assert "forward_profitability_gate" in out["blockers"]
