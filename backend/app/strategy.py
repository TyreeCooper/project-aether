"""Public, testable dual-SMA crossover (long-only spot)."""

from __future__ import annotations


def sma(values: list[float], length: int) -> float | None:
    if length <= 0 or len(values) < length:
        return None
    window = values[-length:]
    return sum(window) / length


def crossover_signal(
    closes: list[float],
    short_len: int,
    long_len: int,
    in_position: bool,
) -> str | None:
    if short_len >= long_len:
        return None
    if len(closes) < long_len + 1:
        return None
    prev_short = sma(closes[:-1], short_len)
    prev_long = sma(closes[:-1], long_len)
    cur_short = sma(closes, short_len)
    cur_long = sma(closes, long_len)
    if (
        prev_short is None
        or prev_long is None
        or cur_short is None
        or cur_long is None
    ):
        return None
    if not in_position and prev_short <= prev_long and cur_short > cur_long:
        return "buy"
    if in_position and prev_short >= prev_long and cur_short < cur_long:
        return "sell"
    return None
