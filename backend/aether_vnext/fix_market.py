"""Provider-neutral FIX 5.0 SP2 market-data boundary for AETHER vNext.

This module implements only public FIX Trading Community application semantics.
It is deliberately not a FIX session engine: logon credentials, CompIDs, sequence
recovery, SSL endpoints, broker-specific symbol conventions, and conformance rules
belong to the approved provider specification.

Supported application messages:
- MarketDataRequest (35=V) application fields for a top-of-book snapshot;
- MarketDataSnapshotFullRefresh (35=W) BBO decoding;
- MarketDataRequestReject (35=Y) decoding.

No order-entry message types exist here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Mapping, Sequence

from aether_vnext.market_data import RawQuote


FIXT_11 = "FIXT.1.1"
FIX50SP2_APPLVER_ID = "9"
FIX_SOH = "\x01"

FIX_MARKET_DATA_REQUEST = "V"
FIX_MARKET_DATA_SNAPSHOT = "W"
FIX_MARKET_DATA_REJECT = "Y"

FIX_BID = "0"
FIX_OFFER = "1"
FIX_TRADE = "2"

FIX_STANDARD_BBO_ADAPTER_VERSION = "fix50sp2_market_snapshot_bbo_v1"


@dataclass(frozen=True, slots=True)
class FixField:
    tag: int
    value: str


@dataclass(frozen=True, slots=True)
class FixMessage:
    fields: tuple[FixField, ...]

    def values(self, tag: int) -> tuple[str, ...]:
        target = int(tag)
        return tuple(row.value for row in self.fields if row.tag == target)

    def first(self, tag: int) -> str | None:
        values = self.values(tag)
        return values[0] if values else None

    @property
    def msg_type(self) -> str | None:
        return self.first(35)


@dataclass(frozen=True, slots=True)
class FixMarketDataEntry:
    entry_type: str
    price: float
    position_no: int | None = None


@dataclass(frozen=True, slots=True)
class FixBboSnapshot:
    md_req_id: str | None
    symbol: str
    bid: float
    ask: float
    last: float | None
    source_timestamp_utc: datetime | None
    entries: tuple[FixMarketDataEntry, ...]


@dataclass(frozen=True, slots=True)
class FixMarketDataReject:
    md_req_id: str | None
    reject_reason: str | None
    text: str | None


def parse_fix_message(raw: str | bytes) -> FixMessage:
    """Parse an ASCII FIX message while preserving duplicate/repeating tags."""
    if isinstance(raw, bytes):
        raw = raw.decode("ascii")
    text = str(raw)
    if not text.strip():
        raise ValueError("FIX message is empty")

    delimiter = FIX_SOH if FIX_SOH in text else "|"
    fields: list[FixField] = []
    for token in text.split(delimiter):
        token = token.strip()
        if not token:
            continue
        if "=" not in token:
            raise ValueError("FIX field missing '=' delimiter")
        raw_tag, value = token.split("=", 1)
        try:
            tag = int(raw_tag)
        except ValueError as exc:
            raise ValueError(f"invalid FIX tag: {raw_tag}") from exc
        if tag <= 0:
            raise ValueError("FIX tags must be positive integers")
        fields.append(FixField(tag=tag, value=value))

    if not fields:
        raise ValueError("FIX message contains no fields")

    begin = next((row.value for row in fields if row.tag == 8), None)
    if begin is not None and begin != FIXT_11:
        raise ValueError(f"unsupported FIX BeginString: {begin}")
    return FixMessage(fields=tuple(fields))


def _parse_fix_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    formats = (
        "%Y%m%d-%H:%M:%S.%f",
        "%Y%m%d-%H:%M:%S",
    )
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"invalid FIX UTCTimestamp: {text}")


def _positive_price(value: str, *, tag: int) -> float:
    try:
        price = float(value)
    except ValueError as exc:
        raise ValueError(f"invalid FIX price tag {tag}: {value}") from exc
    if price <= 0:
        raise ValueError(f"FIX price tag {tag} must be positive")
    return price


def _market_data_entries(message: FixMessage) -> tuple[FixMarketDataEntry, ...]:
    fields = message.fields
    count_index = next(
        (index for index, field in enumerate(fields) if field.tag == 268),
        None,
    )
    if count_index is None:
        raise ValueError("FIX market snapshot missing NoMDEntries(268)")
    try:
        expected_count = int(fields[count_index].value)
    except ValueError as exc:
        raise ValueError("NoMDEntries(268) must be an integer") from exc
    if expected_count <= 0:
        raise ValueError("NoMDEntries(268) must be positive")

    groups: list[list[FixField]] = []
    current: list[FixField] | None = None
    for field in fields[count_index + 1 :]:
        if field.tag == 269:
            if current is not None:
                groups.append(current)
                if len(groups) == expected_count:
                    break
            current = [field]
            continue
        if current is not None:
            current.append(field)
    if current is not None and len(groups) < expected_count:
        groups.append(current)

    if len(groups) != expected_count:
        raise ValueError(
            "NoMDEntries(268) does not match parsed market-data groups"
        )

    entries: list[FixMarketDataEntry] = []
    for group in groups:
        entry_type = group[0].value
        price_field = next((row for row in group if row.tag == 270), None)
        if price_field is None:
            raise ValueError("FIX market-data entry missing MDEntryPx(270)")
        position_field = next((row for row in group if row.tag == 290), None)
        position = None
        if position_field is not None:
            try:
                position = int(position_field.value)
            except ValueError as exc:
                raise ValueError(
                    "MDEntryPositionNo(290) must be an integer"
                ) from exc
            if position <= 0:
                raise ValueError(
                    "MDEntryPositionNo(290) must be positive"
                )
        entries.append(
            FixMarketDataEntry(
                entry_type=entry_type,
                price=_positive_price(price_field.value, tag=270),
                position_no=position,
            )
        )
    return tuple(entries)


def _single_top(
    entries: Sequence[FixMarketDataEntry],
    *,
    entry_type: str,
    name: str,
) -> float | None:
    matching = [row for row in entries if row.entry_type == entry_type]
    if not matching:
        return None
    position_one = [row for row in matching if row.position_no == 1]
    if len(position_one) == 1:
        return position_one[0].price
    if len(matching) == 1:
        return matching[0].price
    raise ValueError(f"ambiguous FIX top-of-book {name}")


def parse_market_data_snapshot(
    raw: str | bytes | FixMessage,
) -> FixBboSnapshot:
    message = raw if isinstance(raw, FixMessage) else parse_fix_message(raw)
    if message.msg_type != FIX_MARKET_DATA_SNAPSHOT:
        raise ValueError("FIX message is not MarketDataSnapshotFullRefresh(35=W)")

    symbol = str(message.first(55) or "").strip()
    if not symbol:
        raise ValueError("FIX market snapshot missing Symbol(55)")

    entries = _market_data_entries(message)
    bid = _single_top(entries, entry_type=FIX_BID, name="bid")
    ask = _single_top(entries, entry_type=FIX_OFFER, name="offer")
    if bid is None or ask is None:
        raise ValueError("FIX BBO snapshot requires bid and offer")
    if bid > ask:
        raise ValueError("FIX BBO snapshot is crossed")

    last = _single_top(entries, entry_type=FIX_TRADE, name="trade")
    source_ts = _parse_fix_timestamp(message.first(60) or message.first(52))
    return FixBboSnapshot(
        md_req_id=message.first(262),
        symbol=symbol,
        bid=bid,
        ask=ask,
        last=last,
        source_timestamp_utc=source_ts,
        entries=entries,
    )


def parse_market_data_reject(
    raw: str | bytes | FixMessage,
) -> FixMarketDataReject:
    message = raw if isinstance(raw, FixMessage) else parse_fix_message(raw)
    if message.msg_type != FIX_MARKET_DATA_REJECT:
        raise ValueError("FIX message is not MarketDataRequestReject(35=Y)")
    return FixMarketDataReject(
        md_req_id=message.first(262),
        reject_reason=message.first(281),
        text=message.first(58),
    )


def top_of_book_snapshot_request_fields(
    *,
    md_req_id: str,
    symbol: str,
) -> tuple[FixField, ...]:
    """Return FIX-standard application fields; a FIX engine owns the header/trailer."""
    request_id = str(md_req_id).strip()
    instrument = str(symbol).strip()
    if not request_id:
        raise ValueError("md_req_id is required")
    if not instrument:
        raise ValueError("symbol is required")
    return (
        FixField(35, FIX_MARKET_DATA_REQUEST),
        FixField(262, request_id),
        FixField(263, "0"),  # Snapshot
        FixField(264, "1"),  # Top of book
        FixField(267, "2"),  # Bid + Offer entry types
        FixField(269, FIX_BID),
        FixField(269, FIX_OFFER),
        FixField(146, "1"),  # One related symbol
        FixField(55, instrument),
    )


def snapshot_to_raw_quote(
    snapshot: FixBboSnapshot,
    *,
    symbol_to_asset: Mapping[str, str],
    venue: str,
    source_id: str,
    received_at_utc: datetime,
    adapter_version: str = FIX_STANDARD_BBO_ADAPTER_VERSION,
) -> RawQuote:
    if received_at_utc.tzinfo is None:
        raise ValueError("received_at_utc must be timezone-aware")
    symbol = snapshot.symbol.strip()
    asset_id = symbol_to_asset.get(symbol)
    if asset_id is None:
        raise ValueError("FIX symbol is not present in reviewed asset binding")
    venue_value = str(venue).strip()
    source_value = str(source_id).strip()
    if not venue_value or not source_value:
        raise ValueError("venue and source_id are required")

    return RawQuote(
        asset_id=str(asset_id).strip().lower(),
        venue=venue_value,
        source_id=source_value,
        bid=snapshot.bid,
        ask=snapshot.ask,
        last=snapshot.last,
        mark=(snapshot.bid + snapshot.ask) / 2.0,
        exchange_ts=snapshot.source_timestamp_utc,
        received_ts=received_at_utc,
        adapter_version=str(adapter_version).strip(),
    )


def render_application_fields(
    fields: Iterable[FixField],
    *,
    delimiter: str = FIX_SOH,
) -> str:
    """Render application fields for handoff to a session engine in tests/tools."""
    delim = str(delimiter)
    if not delim:
        raise ValueError("delimiter is required")
    return delim.join(f"{field.tag}={field.value}" for field in fields) + delim
