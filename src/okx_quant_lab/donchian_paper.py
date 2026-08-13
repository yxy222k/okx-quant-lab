from __future__ import annotations

from dataclasses import dataclass

from okx_quant_lab.okx_public import Candle
from okx_quant_lab.paper import (
    PaperFill,
    PaperState,
    load_paper_state,
    save_paper_state,
)


# The Donchian paper session reuses PaperState/PaperFill and their JSON
# persistence from paper.py; only the signal differs from the SMA session.
__all__ = [
    "DonchianPaperConfig",
    "new_donchian_paper_state",
    "run_donchian_paper_session",
    "donchian_paper_equity",
    "load_paper_state",
    "save_paper_state",
]


@dataclass(frozen=True)
class DonchianPaperConfig:
    inst_id: str
    initial_cash: float = 1_000.0
    entry_window: int = 20
    exit_window: int = 10
    fee_rate: float = 0.001
    slippage_bps: float = 2.0
    trade_fraction: float = 0.5


def new_donchian_paper_state(config: DonchianPaperConfig) -> PaperState:
    return PaperState(cash=config.initial_cash, asset=0.0, last_timestamp_ms=0, fills=[])


def run_donchian_paper_session(
    candles: list[Candle],
    state: PaperState,
    config: DonchianPaperConfig,
) -> PaperState:
    sorted_candles = sorted(candles, key=lambda candle: candle.timestamp_ms)
    closes = [candle.close for candle in sorted_candles]
    cash = state.cash
    asset = state.asset
    fills = list(state.fills)
    last_timestamp_ms = state.last_timestamp_ms
    warmup = max(config.entry_window, config.exit_window) + 1

    for index, candle in enumerate(sorted_candles):
        if candle.timestamp_ms <= state.last_timestamp_ms:
            continue

        if index >= warmup:
            previous_close = closes[index - 1]
            entry_channel_high = max(closes[index - 1 - config.entry_window : index - 1])
            exit_channel_low = min(closes[index - 1 - config.exit_window : index - 1])

            if asset == 0 and cash > 0 and previous_close > entry_channel_high:
                cash, asset, fill = _paper_buy(candle, cash, asset, config)
                fills.append(fill)
            elif asset > 0 and previous_close < exit_channel_low:
                cash, asset, fill = _paper_sell(candle, cash, asset, config)
                fills.append(fill)

        last_timestamp_ms = candle.timestamp_ms

    return PaperState(
        cash=cash,
        asset=asset,
        last_timestamp_ms=last_timestamp_ms,
        fills=fills,
    )


def donchian_paper_equity(
    state: PaperState,
    mark_price: float,
    config: DonchianPaperConfig,
) -> float:
    exit_price = _slipped_price(mark_price, "SELL", config.slippage_bps)
    return state.cash + state.asset * exit_price * (1 - config.fee_rate)


def _paper_buy(
    candle: Candle,
    cash: float,
    asset: float,
    config: DonchianPaperConfig,
) -> tuple[float, float, PaperFill]:
    fill_price = _slipped_price(candle.open, "BUY", config.slippage_bps)
    spend = cash * config.trade_fraction
    fee = spend * config.fee_rate
    quantity = (spend - fee) / fill_price
    cash_after = cash - spend
    asset_after = asset + quantity

    return (
        cash_after,
        asset_after,
        PaperFill(
            timestamp_ms=candle.timestamp_ms,
            side="BUY",
            price=fill_price,
            quantity=quantity,
            fee=fee,
            cash_after=cash_after,
            asset_after=asset_after,
        ),
    )


def _paper_sell(
    candle: Candle,
    cash: float,
    asset: float,
    config: DonchianPaperConfig,
) -> tuple[float, float, PaperFill]:
    fill_price = _slipped_price(candle.open, "SELL", config.slippage_bps)
    gross = asset * fill_price
    fee = gross * config.fee_rate
    cash_after = cash + gross - fee
    asset_after = 0.0

    return (
        cash_after,
        asset_after,
        PaperFill(
            timestamp_ms=candle.timestamp_ms,
            side="SELL",
            price=fill_price,
            quantity=asset,
            fee=fee,
            cash_after=cash_after,
            asset_after=asset_after,
        ),
    )


def _slipped_price(price: float, side: str, slippage_bps: float) -> float:
    slippage = slippage_bps / 10_000
    if side == "BUY":
        return price * (1 + slippage)
    if side == "SELL":
        return price * (1 - slippage)
    raise ValueError(f"unknown side: {side}")
