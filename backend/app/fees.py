"""Single paper friction constant. Env wins."""
from __future__ import annotations

import os

TAKER_FEE = float(os.getenv("AETHER_TAKER_FEE_RATE", "0.0026"))
