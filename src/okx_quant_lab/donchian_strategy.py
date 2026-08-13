from __future__ import annotations

from dataclasses import dataclass

from okx_quant_lab.market_math import (
    close_long,
    liquidation_equity,
    max_drawdown_pct,
    open_long,
)
from okx_quant_lab.okx_public import Candle


@dataclass(frozen=True)
class DonchianBacktestConfig:
    initial_cash: float = 1_000.0
    entry_window: int = 20
    exit_window: int = 10
    fee_rate: float = 0.001
    slippage_bps: float = 2.0
    trade_fraction: float = 0.5


@dataclass(frozen=True)
class DonchianTrade:
    timestamp_ms: int
    side: str
    price: float
    quantity: float
    fee: float


@dataclass(frozen=True)
class DonchianBacktestResult:
    config: DonchianBacktestConfig
    trades: list[DonchianTrade]
    final_equity: float
    return_pct: float
    max_drawdown_pct: float


def run_donchian_breakout_backtest(
    candles: list[Candle],
    config: DonchianBacktestConfig,
) -> DonchianBacktestResult:
    _validate_config(candles, config)

    sorted_candles = sorted(candles, key=lambda candle: candle.timestamp_ms)
    closes = [candle.close for candle in sorted_candles]

    cash = config.initial_cash
    asset = 0.0
    trades: list[DonchianTrade] = []
    equity_values: list[float] = []

    # Signals come only from closed candles before the current one: the
    # previous close must break out of the channel formed by the window of
    # closes before it. Fills happen at the current candle open.
    warmup = max(config.entry_window, config.exit_window) + 1

    for index, candle in enumerate(sorted_candles):
        if index >= warmup:
            previous_close = closes[index - 1]
            entry_channel_high = max(closes[index - 1 - config.entry_window : index - 1])
            exit_channel_low = min(closes[index - 1 - config.exit_window : index - 1])

            if asset == 0 and previous_close > entry_channel_high:
                cash, asset, trade = _buy(candle, cash, asset, config)
                trades.append(trade)
            elif asset > 0 and previous_close < exit_channel_low:
                cash, asset, trade = _sell(candle, cash, asset, config)
                trades.append(trade)

        equity_values.append(_equity(cash, asset, candle.close, config))

    final_equity = equity_values[-1]
    return DonchianBacktestResult(
        config=config,
        trades=trades,
        final_equity=final_equity,
        return_pct=(final_equity / config.initial_cash - 1) * 100,
        max_drawdown_pct=max_drawdown_pct(equity_values),
    )


def _validate_config(candles: list[Candle], config: DonchianBacktestConfig) -> None:
    if config.initial_cash <= 0:
        raise ValueError("initial_cash must be positive")
    if config.entry_window <= 0:
        raise ValueError("entry_window must be positive")
    if config.exit_window <= 0:
        raise ValueError("exit_window must be positive")
    if not 0 <= config.fee_rate < 1:
        raise ValueError("fee_rate must be between 0 and 1")
    if not 0 <= config.slippage_bps < 10_000:
        raise ValueError("slippage_bps must be between 0 and 10000")
    if not 0 < config.trade_fraction <= 1:
        raise ValueError("trade_fraction must be between 0 and 1")
    if len(candles) <= max(config.entry_window, config.exit_window) + 1:
        raise ValueError("not enough candles for the channel windows")


def _buy(
    candle: Candle,
    cash: float,
    asset: float,
    config: DonchianBacktestConfig,
) -> tuple[float, float, DonchianTrade]:
    fill = open_long(
        candle.open, cash, config.fee_rate, config.slippage_bps, config.trade_fraction
    )
    return (
        fill.cash_after,
        asset + fill.quantity,
        DonchianTrade(candle.timestamp_ms, "BUY", fill.fill_price, fill.quantity, fill.fee),
    )


def _sell(
    candle: Candle,
    cash: float,
    asset: float,
    config: DonchianBacktestConfig,
) -> tuple[float, float, DonchianTrade]:
    fill = close_long(candle.open, cash, asset, config.fee_rate, config.slippage_bps)
    return (
        fill.cash_after,
        0.0,
        DonchianTrade(candle.timestamp_ms, "SELL", fill.fill_price, fill.quantity, fill.fee),
    )


def _equity(cash: float, asset: float, price: float, config: DonchianBacktestConfig) -> float:
    return liquidation_equity(cash, asset, price, config.fee_rate, config.slippage_bps)
