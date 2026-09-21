from app.wallet import SpotWallet


def test_wallet_rejects_overspend():
    w = SpotWallet(100.0)
    assert w.buy("eth", 1, 90, fee_rate=0.0)["ok"] is True
    assert w.buy("sol", 1, 20, fee_rate=0.0)["ok"] is False
    assert w.usd < 20


def test_wallet_sell_returns_cash():
    w = SpotWallet(100.0)
    w.buy("btc", 0.001, 10000, fee_rate=0.0)
    out = w.sell("btc", 0.001, 11000, fee_rate=0.0)
    assert out["ok"] is True
    assert w.usd > 99
