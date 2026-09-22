from app.validation import held_out_validation


def _bars(n=2000):
    return [{"ts": 1_700_000_000 + i * 60, "open": 100, "high": 101, "low": 99,
             "close": 100, "volume": 1} for i in range(n)]


def test_holdout_is_chronological_and_disjoint():
    calls = []
    def runner(bars, config, detailed=False):
        calls.append([b["ts"] for b in bars])
        return {"summary": {"expectancy_usd": 1, "profit_factor": 2}}
    out = held_out_validation(_bars(), runner=runner)
    assert out["ok"] is True
    assert max(calls[0]) < min(calls[1])
    assert out["train"]["end"] < out["holdout"]["start"]


def test_gate_requires_nonnegative_expectancy_and_pf_over_one():
    def good(bars, config, detailed=False):
        return {"summary": {"expectancy_usd": 0.01, "profit_factor": 1.01}}
    def bad(bars, config, detailed=False):
        return {"summary": {"expectancy_usd": -0.01, "profit_factor": 2.0}}
    assert held_out_validation(_bars(), runner=good)["profitability_gate_pass"] is True
    assert held_out_validation(_bars(), runner=bad)["profitability_gate_pass"] is False


def test_invalid_history_never_reaches_runner():
    bars = _bars()
    bars[100]["ts"] += 60
    def runner(*args, **kwargs):
        raise AssertionError("runner must not receive invalid evidence")
    out = held_out_validation(bars, runner=runner)
    assert out["ok"] is False
    assert out["reason"] == "invalid_bar_history"
