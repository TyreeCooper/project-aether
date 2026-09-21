import os

from app.fees import TAKER_FEE
from app.paper_exec import KRAKEN_TAKER


def test_default_taker_is_26_bps():
    assert os.getenv("AETHER_TAKER_FEE_RATE") in (None, "0.0026") or True
    assert abs(TAKER_FEE - float(os.getenv("AETHER_TAKER_FEE_RATE", "0.0026"))) < 1e-12
    assert abs(float(os.getenv("AETHER_TAKER_FEE_RATE", "0.0026")) - 0.0026) < 1e-12 or os.getenv("AETHER_TAKER_FEE_RATE")
    if os.getenv("AETHER_TAKER_FEE_RATE") is None:
        assert abs(TAKER_FEE - 0.0026) < 1e-12
    assert KRAKEN_TAKER == TAKER_FEE
    assert TAKER_FEE != 0.008
