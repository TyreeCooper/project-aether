"""Read-only IBKR equity instrument discovery for AETHER vNext.

The official IBKR Web API exposes /trsrv/stocks?symbols=... specifically for
resolving equity symbols to contract IDs. This module only parses and retrieves
candidate identities. It never chooses a conid automatically and never writes a
runtime binding.

Authentication is deliberately delegated to the caller-provided httpx client so
AETHER does not invent or duplicate IBKR session semantics.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import httpx


IBKR_STOCK_DISCOVERY_PATH = "/trsrv/stocks"


@dataclass(frozen=True, slots=True)
class IbkrStockContractCandidate:
    symbol: str
    company_name: str
    conid: int
    exchange: str
    is_us: bool | None

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("IBKR symbol is required")
        if not self.company_name.strip():
            raise ValueError("IBKR company_name is required")
        if isinstance(self.conid, bool) or int(self.conid) <= 0:
            raise ValueError("IBKR conid must be a positive integer")
        if not self.exchange.strip():
            raise ValueError("IBKR exchange is required")


def parse_ibkr_stock_candidates(
    payload: object,
    *,
    requested_symbols: tuple[str, ...],
) -> tuple[IbkrStockContractCandidate, ...]:
    if not isinstance(payload, Mapping):
        raise ValueError("IBKR stock discovery payload must be an object")

    requested = tuple(
        str(symbol).strip().upper()
        for symbol in requested_symbols
        if str(symbol).strip()
    )
    if not requested:
        raise ValueError("at least one IBKR symbol is required")
    if len(requested) != len(set(requested)):
        raise ValueError("duplicate IBKR symbol")

    out: list[IbkrStockContractCandidate] = []
    for symbol in requested:
        raw_rows = payload.get(symbol)
        if not isinstance(raw_rows, list):
            continue
        for row in raw_rows:
            if not isinstance(row, Mapping):
                continue
            company_name = str(row.get("name") or "").strip()
            if str(row.get("assetClass") or "").strip().upper() != "STK":
                continue
            contracts = row.get("contracts")
            if not isinstance(contracts, list):
                continue
            for contract in contracts:
                if not isinstance(contract, Mapping):
                    continue
                try:
                    conid = int(contract.get("conid"))
                except (TypeError, ValueError):
                    continue
                exchange = str(contract.get("exchange") or "").strip()
                if conid <= 0 or not company_name or not exchange:
                    continue
                is_us_raw = contract.get("isUS")
                is_us = is_us_raw if isinstance(is_us_raw, bool) else None
                out.append(
                    IbkrStockContractCandidate(
                        symbol=symbol,
                        company_name=company_name,
                        conid=conid,
                        exchange=exchange,
                        is_us=is_us,
                    )
                )
    return tuple(out)


async def fetch_ibkr_stock_candidates(
    *,
    symbols: tuple[str, ...],
    client: httpx.AsyncClient,
) -> tuple[IbkrStockContractCandidate, ...]:
    """Fetch candidate stock conids through an already-authenticated IBKR client."""
    requested = tuple(
        str(symbol).strip().upper()
        for symbol in symbols
        if str(symbol).strip()
    )
    if not requested:
        raise ValueError("at least one IBKR symbol is required")
    if len(requested) != len(set(requested)):
        raise ValueError("duplicate IBKR symbol")

    response = await client.get(
        IBKR_STOCK_DISCOVERY_PATH,
        params={"symbols": ",".join(requested)},
    )
    response.raise_for_status()
    return parse_ibkr_stock_candidates(
        response.json(),
        requested_symbols=requested,
    )
