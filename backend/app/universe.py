"""Official multi-market paper desk universe.

Out: ten Kraken alts.
In: FX home, index/metal/energy/rates micros, three equity names, BTC/ETH.
Quotes: Kraken still feeds btc/eth. Other books are catalog + paper state until
their venue pipes exist.
"""
from __future__ import annotations

ASSETS: list[dict[str, str | bool]] = [
    {
        "id": "eurusd",
        "name": "Euro / US Dollar",
        "symbol": "EURUSD",
        "pair": "EUR/USD",
        "broker": "tastyfx",
        "venue": "tastyfx",
        "product": "EUR/USD spot",
        "style": "scalp_or_swing",
        "kraken": "",
        "tv": "OANDA:EURUSD",
        "binance": "",
        "paper": True,
    },
    {
        "id": "usdjpy",
        "name": "US Dollar / Japanese Yen",
        "symbol": "USDJPY",
        "pair": "USD/JPY",
        "broker": "tastyfx",
        "venue": "tastyfx",
        "product": "USD/JPY spot",
        "style": "scalp_or_swing",
        "kraken": "",
        "tv": "OANDA:USDJPY",
        "binance": "",
        "paper": True,
    },
    {
        "id": "mes",
        "name": "Micro S&P 500",
        "symbol": "MES",
        "pair": "MES",
        "broker": "ninjatrader",
        "venue": "ninjatrader",
        "product": "MES micro future",
        "style": "day_or_swing",
        "kraken": "",
        "tv": "CME_MINI:MES1!",
        "binance": "",
        "paper": True,
    },
    {
        "id": "mnq",
        "name": "Micro Nasdaq-100",
        "symbol": "MNQ",
        "pair": "MNQ",
        "broker": "ninjatrader",
        "venue": "ninjatrader",
        "product": "MNQ micro future",
        "style": "day_or_swing",
        "kraken": "",
        "tv": "CME_MINI:MNQ1!",
        "binance": "",
        "paper": True,
    },
    {
        "id": "mgc",
        "name": "Micro Gold",
        "symbol": "MGC",
        "pair": "MGC",
        "broker": "ninjatrader",
        "venue": "ninjatrader",
        "product": "MGC micro future",
        "style": "swing",
        "kraken": "",
        "tv": "COMEX:MGC1!",
        "binance": "",
        "paper": True,
    },
    {
        "id": "mcl",
        "name": "Micro Crude Oil",
        "symbol": "MCL",
        "pair": "MCL",
        "broker": "ninjatrader",
        "venue": "ninjatrader",
        "product": "MCL micro future",
        "style": "swing",
        "kraken": "",
        "tv": "NYMEX:MCL1!",
        "binance": "",
        "paper": True,
    },
    {
        "id": "us10y",
        "name": "Micro 10-Year Yield",
        "symbol": "10Y",
        "pair": "10Y",
        "broker": "ninjatrader",
        "venue": "ninjatrader",
        "product": "10Y micro yield future",
        "style": "swing",
        "kraken": "",
        "tv": "CBOT:10Y1!",
        "binance": "",
        "paper": True,
    },
    {
        "id": "nvda",
        "name": "NVIDIA",
        "symbol": "NVDA",
        "pair": "NVDA",
        "broker": "interactive_brokers",
        "venue": "ibkr",
        "product": "NVDA shares",
        "style": "day_or_swing",
        "kraken": "",
        "tv": "NASDAQ:NVDA",
        "binance": "",
        "paper": True,
    },
    {
        "id": "tsla",
        "name": "Tesla",
        "symbol": "TSLA",
        "pair": "TSLA",
        "broker": "interactive_brokers",
        "venue": "ibkr",
        "product": "TSLA shares",
        "style": "day_or_swing",
        "kraken": "",
        "tv": "NASDAQ:TSLA",
        "binance": "",
        "paper": True,
    },
    {
        "id": "pltr",
        "name": "Palantir",
        "symbol": "PLTR",
        "pair": "PLTR",
        "broker": "interactive_brokers",
        "venue": "ibkr",
        "product": "PLTR shares",
        "style": "day_or_swing",
        "kraken": "",
        "tv": "NASDAQ:PLTR",
        "binance": "",
        "paper": True,
    },
    {
        "id": "btc",
        "name": "Bitcoin",
        "symbol": "BTC",
        "pair": "BTC/USD",
        "broker": "kraken",
        "venue": "kraken",
        "product": "BTC/USD spot",
        "style": "swing",
        "kraken": "XBTUSD",
        "tv": "KRAKEN:XBTUSD",
        "binance": "BTCUSD",
        "paper": True,
    },
    {
        "id": "eth",
        "name": "Ethereum",
        "symbol": "ETH",
        "pair": "ETH/USD",
        "broker": "kraken",
        "venue": "kraken",
        "product": "ETH/USD spot",
        "style": "swing",
        "rider_of": "btc",
        "kraken": "ETHUSD",
        "tv": "KRAKEN:ETHUSD",
        "binance": "ETHUSD",
        "paper": True,
    },
]

BY_ID = {str(a["id"]): a for a in ASSETS}
KRAKEN_PAIRS = ",".join(
    str(a["kraken"]) for a in ASSETS if str(a.get("kraken") or "").strip()
)


def public_catalog() -> list[dict[str, str | bool]]:
    rows: list[dict[str, str | bool]] = []
    for a in ASSETS:
        rows.append(
            {
                "id": a["id"],
                "name": a["name"],
                "symbol": a["symbol"],
                "pair": a["pair"],
                "broker": a.get("broker", ""),
                "venue": a.get("venue", ""),
                "product": a.get("product", ""),
                "style": a.get("style", ""),
                "tv": a["tv"],
                "paper": bool(a["paper"]),
                "rider_of": a.get("rider_of", ""),
            }
        )
    return rows


def register_asset(asset: dict[str, str | bool]) -> dict[str, str | bool]:
    asset_id = str(asset["id"]).strip().lower()
    if asset_id in BY_ID:
        return BY_ID[asset_id]
    row = {
        "id": asset_id,
        "name": str(asset.get("name") or asset.get("symbol") or asset_id.upper()),
        "symbol": str(asset["symbol"]).upper(),
        "pair": str(asset.get("pair") or asset["symbol"]).upper(),
        "broker": str(asset.get("broker") or ""),
        "venue": str(asset.get("venue") or ""),
        "product": str(asset.get("product") or ""),
        "style": str(asset.get("style") or ""),
        "kraken": str(asset.get("kraken") or ""),
        "tv": str(asset.get("tv") or ""),
        "binance": str(asset.get("binance") or ""),
        "paper": bool(asset.get("paper", True)),
    }
    if asset.get("rider_of"):
        row["rider_of"] = str(asset["rider_of"])
    ASSETS.append(row)
    BY_ID[asset_id] = row
    return row


def export_assets() -> list[dict[str, str | bool]]:
    return [dict(asset) for asset in ASSETS]
