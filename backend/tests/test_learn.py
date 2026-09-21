from app.learn import STRATEGY_ACTOR_PREFIX, score_exits


def test_live_exit_score_is_strategy_cohorted_and_has_profit_factor():
    fills = [
        {
            "ts": "2026-09-21T10:00:00+00:00",
            "side": "sell",
            "actor": f"{STRATEGY_ACTOR_PREFIX}managed_stop",
            "realized_pnl_usd": 10,
        },
        {
            "ts": "2026-09-21T10:05:00+00:00",
            "side": "sell",
            "actor": f"{STRATEGY_ACTOR_PREFIX}time_stop",
            "realized_pnl_usd": -5,
        },
        {
            "ts": "2026-09-21T10:10:00+00:00",
            "side": "sell",
            "actor": "flatten",
            "realized_pnl_usd": 500,
        },
    ]
    out = score_exits(fills)
    assert out["closed"] == 2
    assert out["ignored_noncohort_sells"] == 1
    assert out["expectancy_usd"] == 2.5
    assert out["profit_factor"] == 2.0
    assert out["cohort"] == STRATEGY_ACTOR_PREFIX
