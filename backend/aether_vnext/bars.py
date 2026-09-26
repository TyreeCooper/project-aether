"""Exchange-timestamp bar construction for replay and paper paths.

No missing bucket is synthesized. A new print may close the prior populated bucket;
empty time buckets simply do not exist.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aether_vnext.market_truth import bar_is_closed


@dataclass(frozen=True, slots=True)
class MarketPrint:
    asset_id: str
    price: float
    volume: float
    exchange_ts: datetime
    received_ts: datetime
    source_id: str

    def __post_init__(self) -> None:
        if self.exchange_ts.tzinfo is None or self.received_ts.tzinfo is None:
            raise ValueError("market print timestamps must be timezone-aware")
        if self.price <= 0:
            raise ValueError("market print price must be positive")
        if self.volume < 0:
            raise ValueError("market print volume cannot be negative")


@dataclass(frozen=True, slots=True)
class Bar:
    asset_id: str
    interval: timedelta
    bucket_open_utc: datetime
    bucket_close_utc: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    first_exchange_ts: datetime
    last_exchange_ts: datetime
    print_count: int
    source_id: str


@dataclass(slots=True)
class _WorkingBar:
    asset_id: str
    interval: timedelta
    bucket_open_utc: datetime
    bucket_close_utc: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    first_exchange_ts: datetime
    last_exchange_ts: datetime
    print_count: int
    source_id: str

    def update(self, print_: MarketPrint) -> None:
        self.high = max(self.high, print_.price)
        self.low = min(self.low, print_.price)
        self.close = print_.price
        self.volume += print_.volume
        self.last_exchange_ts = print_.exchange_ts
        self.print_count += 1

    def freeze(
        self,
        *,
        bucket_close_override_utc: datetime | None = None,
    ) -> Bar:
        close_utc = bucket_close_override_utc or self.bucket_close_utc
        if close_utc.tzinfo is None:
            raise ValueError("bar close timestamp must be timezone-aware")
        if close_utc < self.bucket_open_utc:
            raise ValueError("bar close cannot precede bar open")
        return Bar(
            asset_id=self.asset_id,
            interval=self.interval,
            bucket_open_utc=self.bucket_open_utc,
            bucket_close_utc=close_utc,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            first_exchange_ts=self.first_exchange_ts,
            last_exchange_ts=self.last_exchange_ts,
            print_count=self.print_count,
            source_id=self.source_id,
        )


def bucket_open_utc(
    *,
    exchange_ts: datetime,
    interval: timedelta,
    venue_timezone: str,
) -> datetime:
    if exchange_ts.tzinfo is None:
        raise ValueError("exchange_ts must be timezone-aware")
    seconds = int(interval.total_seconds())
    if seconds <= 0:
        raise ValueError("interval must be positive")

    zone = ZoneInfo(venue_timezone)
    local = exchange_ts.astimezone(zone)

    if seconds >= 86_400:
        local_open = local.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        since_midnight = (
            local.hour * 3600
            + local.minute * 60
            + local.second
        )
        bucket_seconds = (since_midnight // seconds) * seconds
        local_open = local.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        ) + timedelta(seconds=bucket_seconds)

    return local_open.astimezone(timezone.utc)


class ClosedBarBuilder:
    def __init__(
        self,
        *,
        asset_id: str,
        interval: timedelta,
        venue_timezone: str,
    ) -> None:
        if interval.total_seconds() <= 0:
            raise ValueError("interval must be positive")
        self.asset_id = asset_id
        self.interval = interval
        self.venue_timezone = venue_timezone
        self._working: _WorkingBar | None = None

    def push(self, print_: MarketPrint) -> tuple[Bar, ...]:
        if print_.asset_id != self.asset_id:
            raise ValueError("print asset_id does not match builder")
        opened = bucket_open_utc(
            exchange_ts=print_.exchange_ts,
            interval=self.interval,
            venue_timezone=self.venue_timezone,
        )
        closes = opened + self.interval

        if self._working is None:
            self._working = self._start(print_, opened, closes)
            return ()

        current = self._working
        if opened == current.bucket_open_utc:
            current.update(print_)
            return ()

        if opened < current.bucket_open_utc:
            raise ValueError("out-of-order exchange_ts is not accepted by bar builder")

        # New populated bucket. The incoming exchange timestamp is the same
        # exchange-time evidence used by paper and replay to close the prior bar.
        if not bar_is_closed(
            bar_open_utc=current.bucket_open_utc,
            interval=current.interval,
            observation_exchange_ts=print_.exchange_ts,
            observation_received_ts=print_.received_ts,
        ):
            raise AssertionError("future-close violation")

        closed = current.freeze()
        self._working = self._start(print_, opened, closes)
        # Missing intermediate buckets are deliberately absent.
        return (closed,)

    def close_at_session_end(
        self,
        *,
        session_close_utc: datetime,
        received_ts: datetime,
    ) -> tuple[Bar, ...]:
        current = self._working
        if current is None:
            return ()
        if session_close_utc.tzinfo is None or received_ts.tzinfo is None:
            raise ValueError("session timestamps must be timezone-aware")
        if session_close_utc < current.bucket_open_utc:
            raise ValueError("session close cannot precede forming bar")
        if not bar_is_closed(
            bar_open_utc=current.bucket_open_utc,
            interval=current.interval,
            observation_exchange_ts=session_close_utc,
            observation_received_ts=received_ts,
            session_close_utc=session_close_utc,
        ):
            return ()
        closed = current.freeze(
            bucket_close_override_utc=session_close_utc,
        )
        self._working = None
        return (closed,)

    @property
    def forming_bar(self) -> Bar | None:
        return None if self._working is None else self._working.freeze()

    def _start(
        self,
        print_: MarketPrint,
        opened: datetime,
        closes: datetime,
    ) -> _WorkingBar:
        return _WorkingBar(
            asset_id=self.asset_id,
            interval=self.interval,
            bucket_open_utc=opened,
            bucket_close_utc=closes,
            open=print_.price,
            high=print_.price,
            low=print_.price,
            close=print_.price,
            volume=print_.volume,
            first_exchange_ts=print_.exchange_ts,
            last_exchange_ts=print_.exchange_ts,
            print_count=1,
            source_id=print_.source_id,
        )
