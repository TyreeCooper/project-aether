import os

from app import engine as engine_mod
from app.fees import TAKER_FEE
from app.paper_exec import KRAKEN_TAKER


def test_default_taker_is_current_kraken_tier1():
    configured = os.getenv("AETHER_TAKER_FEE_RATE")
    expected = float(configured) if configured is not None else 0.008
    assert abs(TAKER_FEE - expected) < 1e-12
    assert KRAKEN_TAKER == TAKER_FEE
    assert abs(engine_mod.TAKER_FEE - expected) < 1e-12
