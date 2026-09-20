from app.strategy import crossover_signal, sma


def test_sma():
    assert sma([1, 2, 3, 4], 4) == 2.5
    assert sma([1, 2], 3) is None


def test_no_signal_when_warming():
    assert crossover_signal([1, 2, 3], 8, 21, False) is None
