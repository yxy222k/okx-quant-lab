from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpreadStats:
    bid: float
    ask: float
    mid: float
    spread: float
    spread_bps: float


def spread_stats(bid: float, ask: float) -> SpreadStats:
    if bid <= 0:
        raise ValueError("bid must be positive")
    if ask <= 0:
        raise ValueError("ask must be positive")
    if ask < bid:
        raise ValueError("ask must be greater than or equal to bid")

    mid = (bid + ask) / 2
    spread = ask - bid
    spread_bps = (spread / mid) * 10_000
    return SpreadStats(bid=bid, ask=ask, mid=mid, spread=spread, spread_bps=spread_bps)
