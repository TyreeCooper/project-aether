from app.risk import RiskDenyReason, deny_entry


def _base(**kwargs):
    data = dict(
        flatten_lock=False,
        paper_mode=True,
        live_blocked=True,
        qty=0.01,
        position_btc=0.0,
        max_position_btc=0.02,
        equity=10000,
        peak_equity=10000,
        max_drawdown_pct=8,
        daily_realized=0,
        daily_loss_cap=250,
    )
    data.update(kwargs)
    return deny_entry(**data)


def test_allows_clean_paper_entry():
    assert _base() is None


def test_blocks_flatten_lock():
    assert _base(flatten_lock=True) == RiskDenyReason.FLATTEN_LOCK.value


def test_blocks_live_when_not_paper():
    assert _base(paper_mode=False, live_blocked=True) == RiskDenyReason.LIVE_BLOCKED.value


def test_blocks_invalid_qty():
    assert _base(qty=0) == RiskDenyReason.INVALID_QTY.value


def test_blocks_stale_market_data():
    assert _base(market_data_stale=True) == RiskDenyReason.STALE_MARKET_DATA.value


def test_blocks_insufficient_liquidity():
    assert _base(liquidity_ok=False) == RiskDenyReason.INSUFFICIENT_LIQUIDITY.value


def test_blocks_wide_spread():
    assert _base(spread_bps=21, max_spread_bps=20) == RiskDenyReason.SPREAD_TOO_WIDE.value


def test_allows_spread_at_limit():
    assert _base(spread_bps=20, max_spread_bps=20) is None


def test_blocks_size():
    assert _base(qty=0.03) == RiskDenyReason.MAX_POSITION.value


def test_blocks_drawdown_at_threshold():
    assert _base(equity=9200, peak_equity=10000, max_drawdown_pct=8) == RiskDenyReason.MAX_DRAWDOWN.value


def test_blocks_daily_loss_at_threshold():
    assert _base(daily_realized=-250, daily_loss_cap=250) == RiskDenyReason.DAILY_LOSS_CAP.value
