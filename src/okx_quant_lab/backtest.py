from __future__ import annotations

from dataclasses import dataclass

from okx_quant_lab.market_math import (
    close_long,
    liquidation_equity,
    max_drawdown_pct,
    open_long,
    slipped_price,
)
from okx_quant_lab.okx_public import Candle


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 1_000.0
    fast_window: int = 10
    slow_window: int = 30
    fee_rate: float = 0.001
    slippage_bps: float = 0.0
    trade_fraction: float = 1.0


@dataclass(frozen=True)
class Trade:
    timestamp_ms: int
    side: str
    price: float
    quantity: float
    fee: float
    cash_after: float
    asset_after: float


@dataclass(frozen=True)
class EquityPoint:
    timestamp_ms: int
    cash: float
    asset: float
    close: float
    equity: float


@dataclass(frozen=True)
class BacktestResult:
    config: BacktestConfig
    trades: list[Trade]
    equity_curve: list[EquityPoint]
    final_equity: float
    return_pct: float
    buy_and_hold_return_pct: float
    max_drawdown_pct: float


def run_sma_backtest(candles: list[Candle], config: BacktestConfig) -> BacktestResult:
    _validate_inputs(candles, config)

    # Sort defensively so the positional rolling-window logic is chronological
    # regardless of caller (mirrors run_donchian_breakout_backtest). A no-op for
    # the load_candles_csv / paper callers, which already pass ascending data.
    candles = sorted(candles, key=lambda candle: candle.timestamp_ms)
    decisions = sma_wants_long(
        [candle.close for candle in candles], config.fast_window, config.slow_window
    )
    return replay_sma_decisions(candles, decisions, config)


def sma_wants_long(
    closes: list[float],
    fast_window: int,
    slow_window: int,
) -> list[bool | None]:
    """The decision the SMA cross makes AT each index, from the closes strictly
    before it: None during warmup, else fast MA > slow MA. Single source of
    signal truth for backtest, paper replay, and position sizing; the live
    counterpart is dry_run.sma_signal over the candles before that index
    (both fill at the same next open).
    """
    decisions: list[bool | None] = [None] * len(closes)
    # Rolling sums over the closes strictly before the current index, so each
    # step costs O(1) instead of re-slicing and re-summing both windows.
    fast_sum = 0.0
    slow_sum = 0.0

    for index, close in enumerate(closes):
        if index >= slow_window:
            decisions[index] = (fast_sum / fast_window) > (slow_sum / slow_window)
        fast_sum += close
        if index >= fast_window:
            fast_sum -= closes[index - fast_window]
        slow_sum += close
        if index >= slow_window:
            slow_sum -= closes[index - slow_window]

    return decisions


def replay_sma_decisions(
    candles: list[Candle],
    decisions: list[bool | None],
    config: BacktestConfig,
) -> BacktestResult:
    """Execute a precomputed decision sequence (candles ascending, 1:1 with
    decisions). Splitting signal from execution lets position-sizing scans
    reuse one signal pass across many trade fractions."""
    _validate_inputs(candles, config)
    if len(decisions) != len(candles):
        raise ValueError("decisions must align 1:1 with candles")

    cash = config.initial_cash
    asset = 0.0
    trades: list[Trade] = []
    equity_curve: list[EquityPoint] = []

    for index, candle in enumerate(candles):
        wants_long = decisions[index]
        if wants_long is not None:
            if wants_long and asset == 0:
                cash, asset, trade = _buy(candle, cash, asset, config)
                trades.append(trade)
            elif not wants_long and asset > 0:
                cash, asset, trade = _sell(candle, cash, asset, config)
                trades.append(trade)

        equity = liquidation_equity(
            cash, asset, candle.close, config.fee_rate, config.slippage_bps
        )
        equity_curve.append(
            EquityPoint(
                timestamp_ms=candle.timestamp_ms,
                cash=cash,
                asset=asset,
                close=candle.close,
                equity=equity,
            )
        )

    final_equity = equity_curve[-1].equity
    return_pct = _return_pct(config.initial_cash, final_equity)
    buy_and_hold_return_pct = _buy_and_hold_return_pct(candles, config)
    return BacktestResult(
        config=config,
        trades=trades,
        equity_curve=equity_curve,
        final_equity=final_equity,
        return_pct=return_pct,
        buy_and_hold_return_pct=buy_and_hold_return_pct,
        max_drawdown_pct=max_drawdown_pct([point.equity for point in equity_curve]),
    )


def _validate_inputs(candles: list[Candle], config: BacktestConfig) -> None:
    if config.initial_cash <= 0:
        raise ValueError("initial_cash must be positive")
    if config.fast_window <= 0:
        raise ValueError("fast_window must be positive")
    if config.slow_window <= config.fast_window:
        raise ValueError("slow_window must be greater than fast_window")
    if not 0 <= config.fee_rate < 1:
        raise ValueError("fee_rate must be between 0 and 1")
    if not 0 <= config.slippage_bps < 10_000:
        raise ValueError("slippage_bps must be between 0 and 10000")
    if not 0 < config.trade_fraction <= 1:
        raise ValueError("trade_fraction must be between 0 and 1")
    if len(candles) <= config.slow_window:
        raise ValueError("not enough candles for the slow window")


def _buy(
    candle: Candle,
    cash: float,
    asset: float,
    config: BacktestConfig,
) -> tuple[float, float, Trade]:
    fill = open_long(
        candle.open, cash, config.fee_rate, config.slippage_bps, config.trade_fraction
    )
    asset_after = asset + fill.quantity

    return (
        fill.cash_after,
        asset_after,
        Trade(
            timestamp_ms=candle.timestamp_ms,
            side="BUY",
            price=fill.fill_price,
            quantity=fill.quantity,
            fee=fill.fee,
            cash_after=fill.cash_after,
            asset_after=asset_after,
        ),
    )


def _sell(
    candle: Candle,
    cash: float,
    asset: float,
    config: BacktestConfig,
) -> tuple[float, float, Trade]:
    fill = close_long(candle.open, cash, asset, config.fee_rate, config.slippage_bps)

    return (
        fill.cash_after,
        0.0,
        Trade(
            timestamp_ms=candle.timestamp_ms,
            side="SELL",
            price=fill.fill_price,
            quantity=fill.quantity,
            fee=fill.fee,
            cash_after=fill.cash_after,
            asset_after=0.0,
        ),
    )


def _buy_and_hold_return_pct(candles: list[Candle], config: BacktestConfig) -> float:
    first = candles[0]
    last = candles[-1]
    buy_price = slipped_price(first.open, "BUY", config.slippage_bps)
    sell_price = slipped_price(last.close, "SELL", config.slippage_bps)
    asset = config.initial_cash * (1 - config.fee_rate) / buy_price
    final_equity = asset * sell_price * (1 - config.fee_rate)
    return _return_pct(config.initial_cash, final_equity)


def _return_pct(initial_cash: float, final_equity: float) -> float:
    return ((final_equity / initial_cash) - 1) * 100
