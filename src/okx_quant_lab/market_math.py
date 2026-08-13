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


def slipped_price(price: float, side: str, slippage_bps: float) -> float:
    """Worst-case fill price after slippage: a BUY pays more, a SELL receives less."""
    slippage = slippage_bps / 10_000
    if side == "BUY":
        return price * (1 + slippage)
    if side == "SELL":
        return price * (1 - slippage)
    raise ValueError(f"unknown side: {side}")


def max_drawdown_pct(equity_values: list[float]) -> float:
    """Largest peak-to-trough drop over the curve, as a negative percentage."""
    peak = equity_values[0]
    max_drawdown = 0.0
    for equity in equity_values:
        peak = max(peak, equity)
        drawdown = (equity / peak - 1) * 100
        max_drawdown = min(max_drawdown, drawdown)
    return max_drawdown


@dataclass(frozen=True)
class LongOpen:
    fill_price: float
    quantity: float
    fee: float
    spend: float
    cash_after: float


@dataclass(frozen=True)
class LongClose:
    fill_price: float
    quantity: float
    fee: float
    cash_after: float


def open_long(
    price: float,
    cash: float,
    fee_rate: float,
    slippage_bps: float,
    trade_fraction: float,
) -> LongOpen:
    """Spend cash * trade_fraction at a slipped price; the fee comes out of the spend."""
    fill_price = slipped_price(price, "BUY", slippage_bps)
    spend = cash * trade_fraction
    fee = spend * fee_rate
    quantity = (spend - fee) / fill_price
    return LongOpen(
        fill_price=fill_price,
        quantity=quantity,
        fee=fee,
        spend=spend,
        cash_after=cash - spend,
    )


def close_long(
    price: float,
    cash: float,
    asset: float,
    fee_rate: float,
    slippage_bps: float,
) -> LongClose:
    """Sell the whole position at a slipped price; the fee comes out of the gross."""
    fill_price = slipped_price(price, "SELL", slippage_bps)
    gross = asset * fill_price
    fee = gross * fee_rate
    return LongClose(
        fill_price=fill_price,
        quantity=asset,
        fee=fee,
        cash_after=cash + gross - fee,
    )


def liquidation_equity(
    cash: float,
    asset: float,
    price: float,
    fee_rate: float,
    slippage_bps: float,
) -> float:
    """Mark-to-market as if the position were sold right now (slippage + fee)."""
    exit_price = slipped_price(price, "SELL", slippage_bps)
    return cash + asset * exit_price * (1 - fee_rate)
