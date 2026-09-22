from app.forward_evidence import forward_paper_evidence


def _fill(pnl, ts, actor="bot-v3-trend-exit"):
    return {
        "ts": ts,
        "side": "sell",
        "actor": actor,
        "realized_pnl_usd": pnl,
    }


def test_forward_gate_requires_profitability_and_defined_sample():
    fills = [
        _fill(3.0, "2026-09-22T19:00:00+00:00"),
        _fill(-1.0, "2026-09-22T19:05:00+00:00"),
    ]
    out = forward_paper_evidence(fills, minimum_exits=2)
    assert out["profitability_gate_pass"] is True
    assert out["sample_gate_pass"] is True
    assert out["forward_gate_pass"] is True
    assert out["live_trading"] is False


def test_forward_gate_does_not_invent_meaningful_sample_threshold():
    fills = [_fill(3.0, "2026-09-22T19:00:00+00:00")]
    out = forward_paper_evidence(fills)
    assert out["profitability_gate_pass"] is False
    assert out["sample_gate_defined"] is False
    assert out["sample_gate_pass"] is False
    assert out["forward_gate_pass"] is False


def test_noncohort_sells_are_excluded_from_forward_evidence():
    fills = [
        _fill(4.0, "2026-09-22T19:00:00+00:00"),
        _fill(100.0, "2026-09-22T19:01:00+00:00", actor="manual"),
        _fill(-1.0, "2026-09-22T19:02:00+00:00"),
    ]
    out = forward_paper_evidence(fills, minimum_exits=2)
    evidence = out["evidence"]
    assert evidence["closed"] == 2
    assert evidence["ignored_noncohort_sells"] == 1
    assert evidence["realized_pnl_usd"] == 3.0
    assert out["forward_gate_pass"] is True
