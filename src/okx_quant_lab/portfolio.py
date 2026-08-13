from __future__ import annotations

from dataclasses import dataclass

from okx_quant_lab.backtest import BacktestConfig, BacktestResult, run_sma_backtest
from okx_quant_lab.okx_public import Candle


@dataclass(frozen=True)
class PortfolioLeg:
    inst_id: str
    result: BacktestResult


@dataclass(frozen=True)
class PortfolioPoint:
    timestamp_ms: int
    equity: float


@dataclass(frozen=True)
class PortfolioResult:
    legs: list[PortfolioLeg]
    equity_curve: list[PortfolioPoint]
    final_equity: float
    return_pct: float
    max_drawdown_pct: float


def run_equal_weight_portfolio(
    candle_map: dict[str, list[Candle]],
    base_config: BacktestConfig,
    total_cash: float,
) -> PortfolioResult:
    if total_cash <= 0:
        raise ValueError("total_cash must be positive")
    if not candle_map:
        raise ValueError("candle_map must not be empty")

    per_symbol_cash = total_cash / len(candle_map)
    legs: list[PortfolioLeg] = []

    for inst_id, candles in sorted(candle_map.items()):
        config = BacktestConfig(
            initial_cash=per_symbol_cash,
            fast_window=base_config.fast_window,
            slow_window=base_config.slow_window,
            fee_rate=base_config.fee_rate,
            slippage_bps=base_config.slippage_bps,
            trade_fraction=base_config.trade_fraction,
        )
        legs.append(PortfolioLeg(inst_id, run_sma_backtest(candles, config)))

    common_timestamps = _common_timestamps(legs)
    equity_curve = [
        PortfolioPoint(
            timestamp_ms=timestamp_ms,
            equity=sum(_equity_by_timestamp(leg)[timestamp_ms] for leg in legs),
        )
        for timestamp_ms in common_timestamps
    ]
    if not equity_curve:
        raise ValueError("portfolio legs have no overlapping timestamps")

    final_equity = equity_curve[-1].equity
    return PortfolioResult(
        legs=legs,
        equity_curve=equity_curve,
        final_equity=final_equity,
        return_pct=(final_equity / total_cash - 1) * 100,
        max_drawdown_pct=_max_drawdown_pct([point.equity for point in equity_curve]),
    )


def _common_timestamps(legs: list[PortfolioLeg]) -> list[int]:
    timestamp_sets = [
        {point.timestamp_ms for point in leg.result.equity_curve}
        for leg in legs
    ]
    common = set.intersection(*timestamp_sets)
    return sorted(common)


def _equity_by_timestamp(leg: PortfolioLeg) -> dict[int, float]:
    return {
        point.timestamp_ms: point.equity
        for point in leg.result.equity_curve
    }


def _max_drawdown_pct(equity_values: list[float]) -> float:
    peak = equity_values[0]
    max_drawdown = 0.0
    for equity in equity_values:
        peak = max(peak, equity)
        drawdown = (equity / peak - 1) * 100
        max_drawdown = min(max_drawdown, drawdown)
    return max_drawdown
