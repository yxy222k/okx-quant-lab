from __future__ import annotations

from dataclasses import dataclass

from okx_quant_lab.market_math import close_long, liquidation_equity, open_long
from okx_quant_lab.okx_public import Candle
from okx_quant_lab.paper import (
    PaperState,
    load_paper_state,
    paper_buy,
    paper_sell,
    save_paper_state,
)


# The Donchian paper session reuses PaperState/PaperFill, the fill functions,
# and the JSON persistence from paper.py; only the signal differs.
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
                cash, asset, fill = paper_buy(candle, cash, asset, config)
                fills.append(fill)
            elif asset > 0 and previous_close < exit_channel_low:
                cash, asset, fill = paper_sell(candle, cash, asset, config)
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
    return liquidation_equity(
        state.cash, state.asset, mark_price, config.fee_rate, config.slippage_bps
    )
