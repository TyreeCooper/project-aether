"""Public ten-asset Kraken-style paper desk universe."""
from __future__ import annotations

ASSETS: list[dict[str, str | bool]] = [
    {"id": "btc", "name": "Bitcoin", "symbol": "BTC", "pair": "BTC/USD", "kraken": "XBTUSD", "tv": "KRAKEN:XBTUSD", "binance": "BTCUSD", "paper": True},
    {"id": "eth", "name": "Ethereum", "symbol": "ETH", "pair": "ETH/USD", "kraken": "ETHUSD", "tv": "KRAKEN:ETHUSD", "binance": "ETHUSD", "paper": True},
    {"id": "sol", "name": "Solana", "symbol": "SOL", "pair": "SOL/USD", "kraken": "SOLUSD", "tv": "KRAKEN:SOLUSD", "binance": "SOLUSD", "paper": True},
    {"id": "xrp", "name": "XRP", "symbol": "XRP", "pair": "XRP/USD", "kraken": "XRPUSD", "tv": "KRAKEN:XRPUSD", "binance": "XRPUSD", "paper": True},
    {"id": "bnb", "name": "BNB", "symbol": "BNB", "pair": "BNB/USD", "kraken": "BNBUSD", "tv": "KRAKEN:BNBUSD", "binance": "BNBUSD", "paper": True},
    {"id": "ada", "name": "Cardano", "symbol": "ADA", "pair": "ADA/USD", "kraken": "ADAUSD", "tv": "KRAKEN:ADAUSD", "binance": "ADAUSD", "paper": True},
    {"id": "link", "name": "Chainlink", "symbol": "LINK", "pair": "LINK/USD", "kraken": "LINKUSD", "tv": "KRAKEN:LINKUSD", "binance": "LINKUSD", "paper": True},
    {"id": "ton", "name": "Toncoin", "symbol": "TON", "pair": "TON/USD", "kraken": "TONUSD", "tv": "KRAKEN:TONUSD", "binance": "TONUSD", "paper": True},
    {"id": "avax", "name": "Avalanche", "symbol": "AVAX", "pair": "AVAX/USD", "kraken": "AVAXUSD", "tv": "KRAKEN:AVAXUSD", "binance": "AVAXUSD", "paper": True},
    {"id": "sui", "name": "Sui", "symbol": "SUI", "pair": "SUI/USD", "kraken": "SUIUSD", "tv": "KRAKEN:SUIUSD", "binance": "SUIUSD", "paper": True},
]

BY_ID = {str(a["id"]): a for a in ASSETS}
KRAKEN_PAIRS = ",".join(str(a["kraken"]) for a in ASSETS)


def public_catalog() -> list[dict[str, str | bool]]:
    return [
        {
            "id": a["id"],
            "name": a["name"],
            "symbol": a["symbol"],
            "pair": a["pair"],
            "tv": a["tv"],
            "paper": bool(a["paper"]),
        }
        for a in ASSETS
    ]
