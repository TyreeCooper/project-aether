"""Kraken OHLC pair aliases. XBTUSD often answers as XXBTZUSD."""

ALIASES = {
    "XBTUSD": ("XBTUSD", "XXBTZUSD"),
    "XXBTZUSD": ("XXBTZUSD", "XBTUSD"),
    "ETHUSD": ("ETHUSD", "XETHZUSD"),
    "XETHZUSD": ("XETHZUSD", "ETHUSD"),
    "XRPUSD": ("XRPUSD", "XXRPZUSD"),
    "XXRPZUSD": ("XXRPZUSD", "XRPUSD"),
}


def candidates(pair: str) -> tuple[str, ...]:
    key = str(pair or "").upper()
    return ALIASES.get(key, (key,))
