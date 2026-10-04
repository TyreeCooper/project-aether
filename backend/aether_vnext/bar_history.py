"""Point-in-time completed-bar history for AETHER vNext runtime.

The runtime may evaluate strategies only from bars that are already closed. This
container deliberately rejects duplicate/out-of-order bars and never exposes a
forming bar.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import timedelta

from aether_vnext.bars import Bar


@dataclass(frozen=True, slots=True)
class ClosedBarHistorySnapshot:
    asset_id: str
    interval: timedelta
    bars: tuple[Bar, ...]

    @property
    def count(self) -> int:
        return len(self.bars)

    @property
    def latest(self) -> Bar | None:
        return self.bars[-1] if self.bars else None


class ClosedBarHistory:
    def __init__(
        self,
        *,
        asset_id: str,
        interval: timedelta,
        max_bars: int,
    ) -> None:
        asset = str(asset_id).strip().lower()
        if not asset:
            raise ValueError("asset_id is required")
        if interval.total_seconds() <= 0:
            raise ValueError("interval must be positive")
        if int(max_bars) <= 0:
            raise ValueError("max_bars must be positive")

        self.asset_id = asset
        self.interval = interval
        self.max_bars = int(max_bars)
        self._bars: deque[Bar] = deque(maxlen=self.max_bars)

    def append(self, bar: Bar) -> None:
        if bar.asset_id != self.asset_id:
            raise ValueError("bar asset_id does not match history")
        if bar.interval != self.interval:
            raise ValueError("bar interval does not match history")
        if bar.bucket_open_utc.tzinfo is None or bar.bucket_close_utc.tzinfo is None:
            raise ValueError("bar timestamps must be timezone-aware")
        if bar.bucket_close_utc <= bar.bucket_open_utc:
            raise ValueError("bar must be closed after its bucket open")
        if bar.last_exchange_ts >= bar.bucket_close_utc:
            raise ValueError(
                "bar last_exchange_ts must be earlier than bucket close"
            )

        latest = self._bars[-1] if self._bars else None
        if latest is not None:
            if bar.bucket_open_utc <= latest.bucket_open_utc:
                raise ValueError(
                    "completed bars must be appended in strictly increasing order"
                )
            if bar.bucket_close_utc <= latest.bucket_close_utc:
                raise ValueError(
                    "completed bar closes must be strictly increasing"
                )

        self._bars.append(bar)

    def snapshot(self) -> ClosedBarHistorySnapshot:
        return ClosedBarHistorySnapshot(
            asset_id=self.asset_id,
            interval=self.interval,
            bars=tuple(self._bars),
        )

    def last(self, count: int) -> tuple[Bar, ...]:
        n = int(count)
        if n <= 0:
            raise ValueError("count must be positive")
        if n >= len(self._bars):
            return tuple(self._bars)
        bars = tuple(self._bars)
        return bars[-n:]
