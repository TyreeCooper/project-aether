"""Single paper friction constant.

AETHER_TAKER_FEE_RATE may override the default only when the account's actual
Kraken fee tier is known.  The default is deliberately conservative: Kraken
Spot Crypto Tier 1 taker is 0.80% as of 2026-09-21.
"""
from __future__ import annotations

import os

TAKER_FEE = float(os.getenv("AETHER_TAKER_FEE_RATE", "0.008"))
