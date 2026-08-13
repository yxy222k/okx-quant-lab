from __future__ import annotations

from dataclasses import dataclass

from okx_quant_lab.indicators import relative_strength_index
from okx_quant_lab.market_math import (
    close_long,
    liquidation_equity,
    max_drawdown_pct,
    open_long,
)
from okx_quant_lab.okx_public import Candle


@dataclass(frozen=True)
class RsiBacktestConfig:
    initial_cash: float = 1_000.0
    rsi_period: int = 14
    buy_below: float = 35.0
    sell_above: float = 55.0
    fee_rate: float = 0.001
    slippage_bps: float = 2.0
    trade_fraction: float = 0.5


@dataclass(frozen=True)
class RsiTrade:
    timestamp_ms: int
    side: str
    price: float
    quantity: float
    fee: float
    rsi: float


@dataclass(frozen=True)
class RsiBacktestResult:
    config: RsiBacktestConfig
    trades: list[RsiTrade]
    final_equity: float
    return_pct: float
    max_drawdown_pct: float


def run_rsi_mean_reversion_backtest(
    candles: list[Candle],
    config: RsiBacktestConfig,
) -> RsiBacktestResult:
    _validate_config(candles, config)

    sorted_candles = sorted(candles, key=lambda candle: candle.timestamp_ms)
    closes = [candle.close for candle in sorted_candles]
    rsi_values = relative_strength_index(closes, config.rsi_period)

    cash = config.initial_cash
    asset = 0.0
    trades: list[RsiTrade] = []
    equity_values: list[float] = []

    for index, candle in enumerate(sorted_candles):
        current_rsi = rsi_values[index - 1] if index > 0 else None
        if current_rsi is not None:
            if current_rsi < config.buy_below and asset == 0 and cash > 0:
                cash, asset, trade = _buy(candle, cash, asset, current_rsi, config)
                trades.append(trade)
            elif current_rsi > config.sell_above and asset > 0:
                cash, asset, trade = _sell(candle, cash, asset, current_rsi, config)
                trades.append(trade)

        equity_values.append(_equity(cash, asset, candle.close, config))

    final_equity = equity_values[-1]
    return RsiBacktestResult(
        config=config,
        trades=trades,
        final_equity=final_equity,
        return_pct=(final_equity / config.initial_cash - 1) * 100,
        max_drawdown_pct=max_drawdown_pct(equity_values),
    )


def _validate_config(candles: list[Candle], config: RsiBacktestConfig) -> None:
    if config.initial_cash <= 0:
        raise ValueError("initial_cash must be positive")
    if config.rsi_period <= 0:
        raise ValueError("rsi_period must be positive")
    if config.buy_below >= config.sell_above:
        raise ValueError("buy_below must be less than sell_above")
    if not 0 <= config.fee_rate < 1:
        raise ValueError("fee_rate must be between 0 and 1")
    if not 0 <= config.slippage_bps < 10_000:
        raise ValueError("slippage_bps must be between 0 and 10000")
    if not 0 < config.trade_fraction <= 1:
        raise ValueError("trade_fraction must be between 0 and 1")
    if len(candles) <= config.rsi_period + 1:
        raise ValueError("not enough candles for RSI period")


def _buy(
    candle: Candle,
    cash: float,
    asset: float,
    rsi: float,
    config: RsiBacktestConfig,
) -> tuple[float, float, RsiTrade]:
    fill = open_long(
        candle.open, cash, config.fee_rate, config.slippage_bps, config.trade_fraction
    )
    return (
        fill.cash_after,
        asset + fill.quantity,
        RsiTrade(candle.timestamp_ms, "BUY", fill.fill_price, fill.quantity, fill.fee, rsi),
    )


def _sell(
    candle: Candle,
    cash: float,
    asset: float,
    rsi: float,
    config: RsiBacktestConfig,
) -> tuple[float, float, RsiTrade]:
    fill = close_long(candle.open, cash, asset, config.fee_rate, config.slippage_bps)
    return (
        fill.cash_after,
        0.0,
        RsiTrade(candle.timestamp_ms, "SELL", fill.fill_price, fill.quantity, fill.fee, rsi),
    )


def _equity(cash: float, asset: float, price: float, config: RsiBacktestConfig) -> float:
    return liquidation_equity(cash, asset, price, config.fee_rate, config.slippage_bps)
