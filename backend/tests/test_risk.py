from app.risk import deny_entry


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
    assert _base(flatten_lock=True) == "flatten_lock"


def test_blocks_size():
    assert _base(qty=0.03) == "max_position"
