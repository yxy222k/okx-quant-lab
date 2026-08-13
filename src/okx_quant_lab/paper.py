from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path

from okx_quant_lab.market_math import close_long, liquidation_equity, open_long
from okx_quant_lab.okx_public import Candle


@dataclass(frozen=True)
class PaperConfig:
    inst_id: str
    initial_cash: float = 1_000.0
    fast_window: int = 20
    slow_window: int = 50
    fee_rate: float = 0.001
    slippage_bps: float = 2.0
    trade_fraction: float = 0.5


@dataclass(frozen=True)
class PaperFill:
    timestamp_ms: int
    side: str
    price: float
    quantity: float
    fee: float
    cash_after: float
    asset_after: float


@dataclass(frozen=True)
class PaperState:
    cash: float
    asset: float
    last_timestamp_ms: int
    fills: list[PaperFill]


def new_paper_state(config: PaperConfig) -> PaperState:
    return PaperState(
        cash=config.initial_cash,
        asset=0.0,
        last_timestamp_ms=0,
        fills=[],
    )


def run_paper_session(
    candles: list[Candle],
    state: PaperState,
    config: PaperConfig,
) -> PaperState:
    sorted_candles = sorted(candles, key=lambda candle: candle.timestamp_ms)
    cash = state.cash
    asset = state.asset
    fills = list(state.fills)
    last_timestamp_ms = state.last_timestamp_ms

    for index, candle in enumerate(sorted_candles):
        if candle.timestamp_ms <= state.last_timestamp_ms:
            continue

        if index >= config.slow_window:
            previous = sorted_candles[index - config.slow_window : index]
            fast_ma = _mean([row.close for row in previous[-config.fast_window :]])
            slow_ma = _mean([row.close for row in previous])
            wants_long = fast_ma > slow_ma

            if wants_long and asset == 0 and cash > 0:
                cash, asset, fill = _paper_buy(candle, cash, asset, config)
                fills.append(fill)
            elif not wants_long and asset > 0:
                cash, asset, fill = _paper_sell(candle, cash, asset, config)
                fills.append(fill)

        last_timestamp_ms = candle.timestamp_ms

    return PaperState(
        cash=cash,
        asset=asset,
        last_timestamp_ms=last_timestamp_ms,
        fills=fills,
    )


def paper_equity(state: PaperState, mark_price: float, config: PaperConfig) -> float:
    return liquidation_equity(
        state.cash, state.asset, mark_price, config.fee_rate, config.slippage_bps
    )


def save_paper_state(path: Path, state: PaperState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")


def load_paper_state(path: Path) -> PaperState:
    data = json.loads(path.read_text(encoding="utf-8"))
    return PaperState(
        cash=float(data["cash"]),
        asset=float(data["asset"]),
        last_timestamp_ms=int(data["last_timestamp_ms"]),
        fills=[_fill_from_dict(row) for row in data.get("fills", [])],
    )


def _paper_buy(
    candle: Candle,
    cash: float,
    asset: float,
    config: PaperConfig,
) -> tuple[float, float, PaperFill]:
    fill = open_long(
        candle.open, cash, config.fee_rate, config.slippage_bps, config.trade_fraction
    )
    asset_after = asset + fill.quantity

    return (
        fill.cash_after,
        asset_after,
        PaperFill(
            timestamp_ms=candle.timestamp_ms,
            side="BUY",
            price=fill.fill_price,
            quantity=fill.quantity,
            fee=fill.fee,
            cash_after=fill.cash_after,
            asset_after=asset_after,
        ),
    )


def _paper_sell(
    candle: Candle,
    cash: float,
    asset: float,
    config: PaperConfig,
) -> tuple[float, float, PaperFill]:
    fill = close_long(candle.open, cash, asset, config.fee_rate, config.slippage_bps)

    return (
        fill.cash_after,
        0.0,
        PaperFill(
            timestamp_ms=candle.timestamp_ms,
            side="SELL",
            price=fill.fill_price,
            quantity=fill.quantity,
            fee=fill.fee,
            cash_after=fill.cash_after,
            asset_after=0.0,
        ),
    )


def _fill_from_dict(row: dict) -> PaperFill:
    return PaperFill(
        timestamp_ms=int(row["timestamp_ms"]),
        side=row["side"],
        price=float(row["price"]),
        quantity=float(row["quantity"]),
        fee=float(row["fee"]),
        cash_after=float(row["cash_after"]),
        asset_after=float(row["asset_after"]),
    )


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)
