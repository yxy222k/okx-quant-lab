from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from okx_quant_lab.okx_public import Candle
from okx_quant_lab.paper import PaperConfig, PaperState
from okx_quant_lab.state_store import load_ledger, save_ledger_atomic


@dataclass(frozen=True)
class DryRunLimits:
    max_order_usdt: float = 25.0


@dataclass(frozen=True)
class OrderRequest:
    client_order_id: str
    inst_id: str
    side: str
    quote_amount_usdt: float
    base_quantity: float
    reference_price: float
    created_at_ms: int
    reason: str


@dataclass(frozen=True)
class DryRunOrder:
    request: OrderRequest
    status: str
    message: str


def sma_signal(candles: list[Candle], config: PaperConfig) -> str:
    if len(candles) < config.slow_window:
        raise ValueError("not enough candles for SMA signal")

    sorted_candles = sorted(candles, key=lambda candle: candle.timestamp_ms)
    previous = sorted_candles[-config.slow_window :]
    fast_ma = _mean([row.close for row in previous[-config.fast_window :]])
    slow_ma = _mean([row.close for row in previous])
    return "LONG" if fast_ma > slow_ma else "CASH"


def build_sma_order_request(
    candles: list[Candle],
    state: PaperState,
    config: PaperConfig,
) -> OrderRequest | None:
    sorted_candles = sorted(candles, key=lambda candle: candle.timestamp_ms)
    latest = sorted_candles[-1]
    signal = sma_signal(sorted_candles, config)

    if signal == "LONG" and state.asset == 0 and state.cash > 0:
        quote_amount = state.cash * config.trade_fraction
        return OrderRequest(
            client_order_id=_client_order_id(config, latest.timestamp_ms, "BUY"),
            inst_id=config.inst_id,
            side="BUY",
            quote_amount_usdt=quote_amount,
            base_quantity=0.0,
            reference_price=latest.close,
            created_at_ms=latest.timestamp_ms,
            reason=f"SMA({config.fast_window},{config.slow_window}) signal LONG",
        )

    if signal == "CASH" and state.asset > 0:
        return OrderRequest(
            client_order_id=_client_order_id(config, latest.timestamp_ms, "SELL"),
            inst_id=config.inst_id,
            side="SELL",
            quote_amount_usdt=0.0,
            base_quantity=state.asset,
            reference_price=latest.close,
            created_at_ms=latest.timestamp_ms,
            reason=f"SMA({config.fast_window},{config.slow_window}) signal CASH",
        )

    return None


class DryRunOrderManager:
    def __init__(self, orders: list[DryRunOrder] | None = None) -> None:
        self._orders = list(orders or [])

    @property
    def orders(self) -> list[DryRunOrder]:
        return list(self._orders)

    def submit(self, request: OrderRequest, limits: DryRunLimits) -> DryRunOrder:
        existing = self._find_by_client_order_id(request.client_order_id)
        if existing is not None:
            return DryRunOrder(
                request=request,
                status="DUPLICATE",
                message="client_order_id already exists; no new dry-run order recorded",
            )

        blocked_message = _blocked_message(request, limits)
        if blocked_message:
            order = DryRunOrder(
                request=request,
                status="BLOCKED",
                message=blocked_message,
            )
            self._orders.append(order)
            return order

        order = DryRunOrder(
            request=request,
            status="DRY_FILLED",
            message="dry-run fill recorded locally; no exchange order submitted",
        )
        self._orders.append(order)
        return order

    def _find_by_client_order_id(self, client_order_id: str) -> DryRunOrder | None:
        for order in self._orders:
            if order.request.client_order_id == client_order_id:
                return order
        return None


def save_order_ledger(path: Path, orders: list[DryRunOrder]) -> None:
    save_ledger_atomic(path, [asdict(order) for order in orders])


def load_order_ledger(path: Path) -> list[DryRunOrder]:
    return [_order_from_dict(row) for row in load_ledger(path)]


def _blocked_message(request: OrderRequest, limits: DryRunLimits) -> str | None:
    if request.side not in {"BUY", "SELL"}:
        return f"unsupported side: {request.side}"

    notional = _request_notional(request)
    if notional <= 0:
        return "order notional must be positive"
    if notional > limits.max_order_usdt:
        return f"order notional {notional:.2f} exceeds cap {limits.max_order_usdt:.2f}"

    return None


def _request_notional(request: OrderRequest) -> float:
    if request.side == "BUY":
        return request.quote_amount_usdt
    return request.base_quantity * request.reference_price


def _client_order_id(config: PaperConfig, timestamp_ms: int, side: str) -> str:
    return (
        f"dryrun:{config.inst_id}:{timestamp_ms}:{side}:"
        f"sma{config.fast_window}-{config.slow_window}"
    )


def _order_from_dict(row: dict) -> DryRunOrder:
    request = row["request"]
    return DryRunOrder(
        request=OrderRequest(
            client_order_id=request["client_order_id"],
            inst_id=request["inst_id"],
            side=request["side"],
            quote_amount_usdt=float(request["quote_amount_usdt"]),
            base_quantity=float(request["base_quantity"]),
            reference_price=float(request["reference_price"]),
            created_at_ms=int(request["created_at_ms"]),
            reason=request["reason"],
        ),
        status=row["status"],
        message=row["message"],
    )


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)
