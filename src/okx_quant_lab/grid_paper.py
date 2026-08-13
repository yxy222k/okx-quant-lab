from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path

from okx_quant_lab.market_math import liquidation_equity, slipped_price
from okx_quant_lab.okx_public import Candle


@dataclass(frozen=True)
class GridPaperConfig:
    inst_id: str
    range_pct: float = 15.0
    grid_count: int = 10
    initial_cash: float = 1_000.0
    fee_rate: float = 0.001
    # Resting maker orders fill at their level; raise this to model taker fills.
    slippage_bps: float = 0.0


@dataclass(frozen=True)
class GridPaperFill:
    timestamp_ms: int
    side: str
    level_index: int
    price: float
    quantity: float
    fee: float
    cash_after: float


@dataclass(frozen=True)
class GridPaperState:
    cash: float
    levels: list[float]
    holdings: list[float]
    armed: list[bool]
    realized_profit: float
    last_timestamp_ms: int
    fills: list[GridPaperFill]


def new_grid_paper_state(config: GridPaperConfig, reference_price: float) -> GridPaperState:
    _validate_config(config)
    if reference_price <= 0:
        raise ValueError("reference_price must be positive")

    lower = reference_price * (1 - config.range_pct / 100)
    upper = reference_price * (1 + config.range_pct / 100)
    step = (upper - lower) / config.grid_count
    levels = [lower + index * step for index in range(config.grid_count + 1)]

    return GridPaperState(
        cash=config.initial_cash,
        levels=levels,
        holdings=[0.0 for _ in range(config.grid_count)],
        armed=[level < reference_price for level in levels[:-1]],
        realized_profit=0.0,
        last_timestamp_ms=0,
        fills=[],
    )


def run_grid_paper_session(
    candles: list[Candle],
    state: GridPaperState,
    config: GridPaperConfig,
) -> GridPaperState:
    _validate_config(config)

    sorted_candles = sorted(candles, key=lambda candle: candle.timestamp_ms)
    levels = state.levels
    slot_cash = config.initial_cash / config.grid_count

    cash = state.cash
    holdings = list(state.holdings)
    armed = list(state.armed)
    realized_profit = state.realized_profit
    fills = list(state.fills)
    last_timestamp_ms = state.last_timestamp_ms

    for candle in sorted_candles:
        if candle.timestamp_ms <= state.last_timestamp_ms:
            continue

        # Sells first: a slot bought in this candle cannot also sell in it.
        for index in range(config.grid_count):
            if holdings[index] > 0 and candle.high >= levels[index + 1]:
                fill_price = slipped_price(levels[index + 1], "SELL", config.slippage_bps)
                quantity = holdings[index]
                gross = quantity * fill_price
                fee = gross * config.fee_rate
                cash += gross - fee
                holdings[index] = 0.0
                realized_profit += gross - fee - slot_cash
                fills.append(
                    GridPaperFill(
                        timestamp_ms=candle.timestamp_ms,
                        side="SELL",
                        level_index=index + 1,
                        price=fill_price,
                        quantity=quantity,
                        fee=fee,
                        cash_after=cash,
                    )
                )

        for index in range(config.grid_count):
            if armed[index] and holdings[index] == 0 and candle.low <= levels[index]:
                fill_price = slipped_price(levels[index], "BUY", config.slippage_bps)
                fee = slot_cash * config.fee_rate
                quantity = (slot_cash - fee) / fill_price
                cash -= slot_cash
                holdings[index] = quantity
                armed[index] = False
                fills.append(
                    GridPaperFill(
                        timestamp_ms=candle.timestamp_ms,
                        side="BUY",
                        level_index=index,
                        price=fill_price,
                        quantity=quantity,
                        fee=fee,
                        cash_after=cash,
                    )
                )

        for index in range(config.grid_count):
            if holdings[index] == 0 and not armed[index] and candle.close > levels[index]:
                armed[index] = True

        last_timestamp_ms = candle.timestamp_ms

    return GridPaperState(
        cash=cash,
        levels=levels,
        holdings=holdings,
        armed=armed,
        realized_profit=realized_profit,
        last_timestamp_ms=last_timestamp_ms,
        fills=fills,
    )


def grid_paper_equity(state: GridPaperState, mark_price: float, config: GridPaperConfig) -> float:
    return liquidation_equity(
        state.cash, sum(state.holdings), mark_price, config.fee_rate, config.slippage_bps
    )


def open_slot_count(state: GridPaperState) -> int:
    return sum(1 for quantity in state.holdings if quantity > 0)


def save_grid_paper_state(path: Path, state: GridPaperState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")


def load_grid_paper_state(path: Path) -> GridPaperState:
    data = json.loads(path.read_text(encoding="utf-8"))
    return GridPaperState(
        cash=float(data["cash"]),
        levels=[float(value) for value in data["levels"]],
        holdings=[float(value) for value in data["holdings"]],
        armed=[bool(value) for value in data["armed"]],
        realized_profit=float(data["realized_profit"]),
        last_timestamp_ms=int(data["last_timestamp_ms"]),
        fills=[_fill_from_dict(row) for row in data.get("fills", [])],
    )


def _validate_config(config: GridPaperConfig) -> None:
    if config.initial_cash <= 0:
        raise ValueError("initial_cash must be positive")
    if not 0 < config.range_pct < 100:
        raise ValueError("range_pct must be between 0 and 100")
    if config.grid_count < 2:
        raise ValueError("grid_count must be at least 2")
    if not 0 <= config.fee_rate < 1:
        raise ValueError("fee_rate must be between 0 and 1")
    if not 0 <= config.slippage_bps < 10_000:
        raise ValueError("slippage_bps must be between 0 and 10000")


def _fill_from_dict(row: dict) -> GridPaperFill:
    return GridPaperFill(
        timestamp_ms=int(row["timestamp_ms"]),
        side=row["side"],
        level_index=int(row["level_index"]),
        price=float(row["price"]),
        quantity=float(row["quantity"]),
        fee=float(row["fee"]),
        cash_after=float(row["cash_after"]),
    )

