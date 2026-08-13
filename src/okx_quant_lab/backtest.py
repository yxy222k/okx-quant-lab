from __future__ import annotations

from dataclasses import dataclass

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

    cash = config.initial_cash
    asset = 0.0
    trades: list[Trade] = []
    equity_curve: list[EquityPoint] = []

    closes = [candle.close for candle in candles]
    # Rolling sums over the closes strictly before the current candle, so each
    # step costs O(1) instead of re-slicing and re-summing both windows.
    fast_sum = 0.0
    slow_sum = 0.0

    for index, candle in enumerate(candles):
        if index >= config.slow_window:
            fast_ma = fast_sum / config.fast_window
            slow_ma = slow_sum / config.slow_window
            wants_long = fast_ma > slow_ma

            if wants_long and asset == 0:
                cash, asset, trade = _buy(candle, cash, asset, config)
                trades.append(trade)
            elif not wants_long and asset > 0:
                cash, asset, trade = _sell(candle, cash, asset, config)
                trades.append(trade)

        fast_sum += closes[index]
        if index >= config.fast_window:
            fast_sum -= closes[index - config.fast_window]
        slow_sum += closes[index]
        if index >= config.slow_window:
            slow_sum -= closes[index - config.slow_window]

        equity = _liquidation_equity(cash, asset, candle.close, config)
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
    max_drawdown_pct = _max_drawdown_pct([point.equity for point in equity_curve])

    return BacktestResult(
        config=config,
        trades=trades,
        equity_curve=equity_curve,
        final_equity=final_equity,
        return_pct=return_pct,
        buy_and_hold_return_pct=buy_and_hold_return_pct,
        max_drawdown_pct=max_drawdown_pct,
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
    fill_price = _slipped_price(candle.open, "BUY", config.slippage_bps)
    spend = cash * config.trade_fraction
    fee = spend * config.fee_rate
    quantity = (spend - fee) / fill_price
    cash_after = cash - spend
    asset_after = asset + quantity

    return (
        cash_after,
        asset_after,
        Trade(
            timestamp_ms=candle.timestamp_ms,
            side="BUY",
            price=fill_price,
            quantity=quantity,
            fee=fee,
            cash_after=cash_after,
            asset_after=asset_after,
        ),
    )


def _sell(
    candle: Candle,
    cash: float,
    asset: float,
    config: BacktestConfig,
) -> tuple[float, float, Trade]:
    fill_price = _slipped_price(candle.open, "SELL", config.slippage_bps)
    gross = asset * fill_price
    fee = gross * config.fee_rate
    cash_after = cash + gross - fee
    asset_after = 0.0

    return (
        cash_after,
        asset_after,
        Trade(
            timestamp_ms=candle.timestamp_ms,
            side="SELL",
            price=fill_price,
            quantity=asset,
            fee=fee,
            cash_after=cash_after,
            asset_after=asset_after,
        ),
    )


def _liquidation_equity(
    cash: float,
    asset: float,
    price: float,
    config: BacktestConfig,
) -> float:
    sell_price = _slipped_price(price, "SELL", config.slippage_bps)
    return cash + asset * sell_price * (1 - config.fee_rate)


def _buy_and_hold_return_pct(candles: list[Candle], config: BacktestConfig) -> float:
    first = candles[0]
    last = candles[-1]
    buy_price = _slipped_price(first.open, "BUY", config.slippage_bps)
    sell_price = _slipped_price(last.close, "SELL", config.slippage_bps)
    asset = config.initial_cash * (1 - config.fee_rate) / buy_price
    final_equity = asset * sell_price * (1 - config.fee_rate)
    return _return_pct(config.initial_cash, final_equity)


def _return_pct(initial_cash: float, final_equity: float) -> float:
    return ((final_equity / initial_cash) - 1) * 100


def _max_drawdown_pct(equity_values: list[float]) -> float:
    peak = equity_values[0]
    max_drawdown = 0.0

    for equity in equity_values:
        peak = max(peak, equity)
        drawdown = (equity / peak - 1) * 100
        max_drawdown = min(max_drawdown, drawdown)

    return max_drawdown


def _slipped_price(price: float, side: str, slippage_bps: float) -> float:
    slippage = slippage_bps / 10_000
    if side == "BUY":
        return price * (1 + slippage)
    if side == "SELL":
        return price * (1 - slippage)
    raise ValueError(f"unknown side: {side}")
