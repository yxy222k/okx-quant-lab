from __future__ import annotations

from dataclasses import dataclass

from okx_quant_lab.market_math import liquidation_equity, max_drawdown_pct, slipped_price
from okx_quant_lab.okx_public import Candle


@dataclass(frozen=True)
class GridBacktestConfig:
    lower_price: float
    upper_price: float
    grid_count: int = 10
    initial_cash: float = 1_000.0
    fee_rate: float = 0.001
    # Resting maker orders fill at their level, so 0 is a fair default here.
    # Set this above 0 to model taker-style execution when price crosses a level.
    slippage_bps: float = 0.0


@dataclass(frozen=True)
class GridFill:
    timestamp_ms: int
    side: str
    level_index: int
    price: float
    quantity: float
    fee: float


@dataclass(frozen=True)
class GridBacktestResult:
    config: GridBacktestConfig
    fills: list[GridFill]
    final_equity: float
    return_pct: float
    max_drawdown_pct: float
    round_trips: int
    realized_profit: float
    open_slots: int
    unrealized_pnl: float
    candles_below_range: int
    buy_and_hold_return_pct: float


def grid_config_from_reference(
    reference_price: float,
    range_pct: float,
    grid_count: int = 10,
    initial_cash: float = 1_000.0,
    fee_rate: float = 0.001,
    slippage_bps: float = 0.0,
) -> GridBacktestConfig:
    if reference_price <= 0:
        raise ValueError("reference_price must be positive")
    if not 0 < range_pct < 100:
        raise ValueError("range_pct must be between 0 and 100")

    return GridBacktestConfig(
        lower_price=reference_price * (1 - range_pct / 100),
        upper_price=reference_price * (1 + range_pct / 100),
        grid_count=grid_count,
        initial_cash=initial_cash,
        fee_rate=fee_rate,
        slippage_bps=slippage_bps,
    )


def run_grid_backtest(candles: list[Candle], config: GridBacktestConfig) -> GridBacktestResult:
    _validate_inputs(candles, config)

    sorted_candles = sorted(candles, key=lambda candle: candle.timestamp_ms)
    levels = _grid_levels(config)
    slot_cash = config.initial_cash / config.grid_count

    # Slot i buys with a limit order at levels[i] and sells at levels[i + 1].
    # A buy order is only "armed" once price is above its level, so the grid
    # never chases price upward by buying above the market.
    holdings = [0.0 for _ in range(config.grid_count)]
    armed = [level < sorted_candles[0].open for level in levels[:-1]]

    cash = config.initial_cash
    fills: list[GridFill] = []
    equity_values: list[float] = []
    round_trips = 0
    realized_profit = 0.0
    candles_below_range = 0

    for candle in sorted_candles:
        # Sells first: a slot bought in this candle cannot also sell in it,
        # because the intra-candle price path is unknown.
        for index in range(config.grid_count):
            if holdings[index] > 0 and candle.high >= levels[index + 1]:
                fill_price = slipped_price(levels[index + 1], "SELL", config.slippage_bps)
                quantity = holdings[index]
                gross = quantity * fill_price
                fee = gross * config.fee_rate
                cash += gross - fee
                holdings[index] = 0.0
                round_trips += 1
                realized_profit += gross - fee - slot_cash
                fills.append(
                    GridFill(
                        timestamp_ms=candle.timestamp_ms,
                        side="SELL",
                        level_index=index + 1,
                        price=fill_price,
                        quantity=quantity,
                        fee=fee,
                    )
                )

        for index in range(config.grid_count):
            if (
                armed[index]
                and holdings[index] == 0
                and candle.low <= levels[index]
                and cash >= slot_cash
            ):
                fill_price = slipped_price(levels[index], "BUY", config.slippage_bps)
                fee = slot_cash * config.fee_rate
                quantity = (slot_cash - fee) / fill_price
                cash -= slot_cash
                holdings[index] = quantity
                armed[index] = False
                fills.append(
                    GridFill(
                        timestamp_ms=candle.timestamp_ms,
                        side="BUY",
                        level_index=index,
                        price=fill_price,
                        quantity=quantity,
                        fee=fee,
                    )
                )

        # Re-arm empty slots the price has moved back above.
        for index in range(config.grid_count):
            if holdings[index] == 0 and not armed[index] and candle.close > levels[index]:
                armed[index] = True

        if candle.close < config.lower_price:
            candles_below_range += 1

        equity_values.append(_mark_to_market(cash, holdings, candle.close, config))

    final_equity = equity_values[-1]
    last_exit_price = slipped_price(sorted_candles[-1].close, "SELL", config.slippage_bps)
    unrealized_pnl = sum(
        quantity * last_exit_price * (1 - config.fee_rate) - slot_cash
        for quantity in holdings
        if quantity > 0
    )

    return GridBacktestResult(
        config=config,
        fills=fills,
        final_equity=final_equity,
        return_pct=(final_equity / config.initial_cash - 1) * 100,
        max_drawdown_pct=max_drawdown_pct(equity_values),
        round_trips=round_trips,
        realized_profit=realized_profit,
        open_slots=sum(1 for quantity in holdings if quantity > 0),
        unrealized_pnl=unrealized_pnl,
        candles_below_range=candles_below_range,
        buy_and_hold_return_pct=_buy_and_hold_return_pct(sorted_candles, config),
    )


def _validate_inputs(candles: list[Candle], config: GridBacktestConfig) -> None:
    if config.initial_cash <= 0:
        raise ValueError("initial_cash must be positive")
    if config.lower_price <= 0:
        raise ValueError("lower_price must be positive")
    if config.upper_price <= config.lower_price:
        raise ValueError("upper_price must be greater than lower_price")
    if config.grid_count < 2:
        raise ValueError("grid_count must be at least 2")
    if not 0 <= config.fee_rate < 1:
        raise ValueError("fee_rate must be between 0 and 1")
    if not 0 <= config.slippage_bps < 10_000:
        raise ValueError("slippage_bps must be between 0 and 10000")
    if not candles:
        raise ValueError("need at least one candle")


def _grid_levels(config: GridBacktestConfig) -> list[float]:
    step = (config.upper_price - config.lower_price) / config.grid_count
    return [config.lower_price + index * step for index in range(config.grid_count + 1)]


def _mark_to_market(
    cash: float,
    holdings: list[float],
    price: float,
    config: GridBacktestConfig,
) -> float:
    return liquidation_equity(cash, sum(holdings), price, config.fee_rate, config.slippage_bps)


def _buy_and_hold_return_pct(candles: list[Candle], config: GridBacktestConfig) -> float:
    asset = config.initial_cash * (1 - config.fee_rate) / candles[0].open
    final_equity = asset * candles[-1].close * (1 - config.fee_rate)
    return (final_equity / config.initial_cash - 1) * 100

