from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

from okx_quant_lab.demo_execution import DemoOrderExecutor, quantize_to_lot
from okx_quant_lab.dry_run import OrderRequest
from okx_quant_lab.okx_public import Candle, InstrumentSpec
from okx_quant_lab.state_store import load_versioned_json, save_json_atomic


@dataclass(frozen=True)
class DemoGridConfig:
    inst_id: str = "SOL-USDT"
    range_pct: float = 15.0
    grid_count: int = 10
    allocation_usdt: float = 100.0
    max_daily_loss_pct: float = 3.0

    @property
    def slot_cash(self) -> float:
        return self.allocation_usdt / self.grid_count


@dataclass(frozen=True)
class DemoGridState:
    cash: float
    levels: list[float]
    holdings: list[float]
    armed: list[bool]
    realized_profit: float
    last_timestamp_ms: int
    day_utc: str
    day_start_equity: float
    breaker_tripped: bool
    # Timestamp of the deploy candle, frozen at deployment. Anchors the
    # reconciliation replay window so it survives candle-file trimming; 0 means
    # unknown (legacy state written before this field existed).
    deploy_timestamp_ms: int = 0


def new_demo_grid_state(config: DemoGridConfig, reference_price: float) -> DemoGridState:
    if reference_price <= 0:
        raise ValueError("reference_price must be positive")

    lower = reference_price * (1 - config.range_pct / 100)
    upper = reference_price * (1 + config.range_pct / 100)
    step = (upper - lower) / config.grid_count
    levels = [lower + index * step for index in range(config.grid_count + 1)]

    return DemoGridState(
        cash=config.allocation_usdt,
        levels=levels,
        holdings=[0.0 for _ in range(config.grid_count)],
        armed=[level < reference_price for level in levels[:-1]],
        realized_profit=0.0,
        last_timestamp_ms=0,
        day_utc="",
        day_start_equity=config.allocation_usdt,
        breaker_tripped=False,
        deploy_timestamp_ms=0,
    )


def advance_demo_grid(
    candles: list[Candle],
    state: DemoGridState,
    config: DemoGridConfig,
    executor: DemoOrderExecutor,
    spec: InstrumentSpec,
    confirmed: bool,
) -> tuple[DemoGridState, list[str]]:
    """Process newly closed candles; submit demo orders for triggered levels.

    Grid semantics here are close-confirmed: a slot buys when a candle CLOSES
    at or below its level and sells when a candle closes at or above the next
    level up. Fills are market orders, so fill price minus level price is the
    measured execution gap versus the paper grid's limit-fill assumption.
    """
    sorted_candles = sorted(candles, key=lambda candle: candle.timestamp_ms)
    levels = state.levels
    events: list[str] = []

    cash = state.cash
    holdings = list(state.holdings)
    armed = list(state.armed)
    realized_profit = state.realized_profit
    last_timestamp_ms = state.last_timestamp_ms
    day_utc = state.day_utc
    day_start_equity = state.day_start_equity
    breaker_tripped = state.breaker_tripped

    for candle in sorted_candles:
        if candle.timestamp_ms <= state.last_timestamp_ms:
            continue
        # Defence in depth: only closed bars drive orders. fetch_candles already
        # drops unconfirmed bars, but never let a still-forming candle place a
        # live order if a caller ever passes one through.
        if not candle.confirmed:
            continue

        equity = cash + sum(holdings) * candle.close
        candle_day = _utc_day(candle.timestamp_ms)
        if candle_day != day_utc:
            # Intentional definition: the daily-loss baseline is the equity at
            # the first processed bar of the UTC day (marked before that bar's
            # orders), so the breaker measures intraday loss from the day's
            # open, not from the prior day's close. An overnight gap down is
            # therefore excluded from the day's loss figure. Left as-is on
            # purpose — changing it alters live circuit-breaker behaviour.
            day_utc = candle_day
            day_start_equity = equity
            breaker_tripped = False

        if not breaker_tripped:
            loss_pct = (equity / day_start_equity - 1) * 100 if day_start_equity > 0 else 0.0
            if loss_pct < -config.max_daily_loss_pct:
                breaker_tripped = True
                events.append(
                    f"CIRCUIT BREAKER tripped: day loss {loss_pct:.2f}% "
                    f"exceeds {config.max_daily_loss_pct:.2f}% -- no more orders today"
                )

        if not breaker_tripped:
            # Sells first: a slot bought on this candle cannot sell on it.
            for index in range(config.grid_count):
                if holdings[index] > 0 and candle.close >= levels[index + 1]:
                    quantity = quantize_to_lot(holdings[index], spec.lot_size)
                    if quantity < spec.min_size:
                        holdings[index] = 0.0
                        events.append(f"slot {index}: dust below min size dropped")
                        continue
                    record = executor.submit(
                        _sell_request(config, candle, index, quantity, levels[index + 1]),
                        confirmed=confirmed,
                    )
                    events.append(_describe(record, target=levels[index + 1]))
                    if record.status == "FILLED":
                        quote_currency = config.inst_id.split("-")[1]
                        # Net the sell fee only when it is charged in the quote
                        # currency (the default). Fees paid in a third currency
                        # (e.g. OKB with the fee discount enabled) are not netted
                        # here — see the known-limitations note in the README.
                        proceeds = record.fill_quantity * record.fill_price + (
                            record.fee if record.fee_currency == quote_currency else 0.0
                        )
                        cash += proceeds
                        realized_profit += proceeds - config.slot_cash
                        holdings[index] = 0.0

            for index in range(config.grid_count):
                if (
                    armed[index]
                    and holdings[index] == 0
                    and candle.close <= levels[index]
                    and cash >= config.slot_cash
                ):
                    record = executor.submit(
                        _buy_request(config, candle, index, levels[index]),
                        confirmed=confirmed,
                    )
                    events.append(_describe(record, target=levels[index]))
                    if record.status == "FILLED":
                        base_currency = config.inst_id.split("-")[0]
                        received = record.fill_quantity + (
                            record.fee if record.fee_currency == base_currency else 0.0
                        )
                        cash -= config.slot_cash
                        holdings[index] = received
                        armed[index] = False

        for index in range(config.grid_count):
            if holdings[index] == 0 and not armed[index] and candle.close > levels[index]:
                armed[index] = True

        last_timestamp_ms = candle.timestamp_ms

    new_state = DemoGridState(
        cash=cash,
        levels=levels,
        holdings=holdings,
        armed=armed,
        realized_profit=realized_profit,
        last_timestamp_ms=last_timestamp_ms,
        day_utc=day_utc,
        day_start_equity=day_start_equity,
        breaker_tripped=breaker_tripped,
        deploy_timestamp_ms=state.deploy_timestamp_ms,
    )
    return new_state, events


def demo_grid_equity(state: DemoGridState, mark_price: float) -> float:
    return state.cash + sum(state.holdings) * mark_price


def open_slot_count(state: DemoGridState) -> int:
    return sum(1 for quantity in state.holdings if quantity > 0)


def save_demo_grid_state(path: Path, state: DemoGridState) -> None:
    save_json_atomic(path, asdict(state), schema_version=1)


def load_demo_grid_state(path: Path) -> DemoGridState:
    data = load_versioned_json(path, current_version=1)
    return DemoGridState(
        cash=float(data["cash"]),
        levels=[float(value) for value in data["levels"]],
        holdings=[float(value) for value in data["holdings"]],
        armed=[bool(value) for value in data["armed"]],
        realized_profit=float(data["realized_profit"]),
        last_timestamp_ms=int(data["last_timestamp_ms"]),
        day_utc=data["day_utc"],
        day_start_equity=float(data["day_start_equity"]),
        breaker_tripped=bool(data["breaker_tripped"]),
        deploy_timestamp_ms=int(data.get("deploy_timestamp_ms", 0)),
    )


def _buy_request(
    config: DemoGridConfig,
    candle: Candle,
    level_index: int,
    level_price: float,
) -> OrderRequest:
    return OrderRequest(
        client_order_id=(
            f"demogrid:{config.inst_id}:{candle.timestamp_ms}:BUY:L{level_index}"
        ),
        inst_id=config.inst_id,
        side="BUY",
        quote_amount_usdt=config.slot_cash,
        base_quantity=0.0,
        reference_price=candle.close,
        created_at_ms=candle.timestamp_ms,
        reason=f"grid buy: close {candle.close:.4f} <= level {level_price:.4f}",
    )


def _sell_request(
    config: DemoGridConfig,
    candle: Candle,
    level_index: int,
    quantity: float,
    target_price: float,
) -> OrderRequest:
    return OrderRequest(
        client_order_id=(
            f"demogrid:{config.inst_id}:{candle.timestamp_ms}:SELL:L{level_index}"
        ),
        inst_id=config.inst_id,
        side="SELL",
        quote_amount_usdt=0.0,
        base_quantity=quantity,
        reference_price=candle.close,
        created_at_ms=candle.timestamp_ms,
        reason=f"grid sell: close {candle.close:.4f} >= level {target_price:.4f}",
    )


def _describe(record, target: float) -> str:
    request = record.request
    line = f"{request.side} {request.inst_id} @level {target:.4f} -> {record.status}"
    if record.status == "FILLED":
        gap_bps = 0.0
        if target > 0 and record.fill_price > 0:
            direction = 1 if request.side == "BUY" else -1
            gap_bps = direction * (record.fill_price / target - 1) * 10_000
        line += (
            f" fill={record.fill_price:.4f} qty={record.fill_quantity:.6f} "
            f"exec_gap={gap_bps:+.1f}bps"
        )
    else:
        line += f" ({record.message})"
    return line


def _utc_day(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).date().isoformat()
