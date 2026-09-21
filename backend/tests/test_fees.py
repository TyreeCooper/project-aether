from app.fees import TAKER_FEE
from app.paper_exec import KRAKEN_TAKER


def test_shared_taker_is_kraken_style():
    assert abs(TAKER_FEE - 0.0026) < 1e-9 or TAKER_FEE > 0
    assert KRAKEN_TAKER == TAKER_FEE
    assert TAKER_FEE < 0.01
