from __future__ import annotations

from dataclasses import dataclass

from okx_quant_lab.backtest import (
    BacktestConfig,
    BacktestResult,
    replay_sma_decisions,
    run_sma_backtest,
    sma_wants_long,
)
from okx_quant_lab.okx_public import Candle


@dataclass(frozen=True)
class RiskLimits:
    max_drawdown_pct: float = -10.0
    min_trades: int = 4
    max_exposure_pct: float = 80.0


@dataclass(frozen=True)
class RiskReport:
    return_pct: float
    max_drawdown_pct: float
    return_over_drawdown: float
    exposure_pct: float
    trades: int
    passed: bool
    notes: list[str]


@dataclass(frozen=True)
class PositionSizeResult:
    trade_fraction: float
    final_equity: float
    return_pct: float
    max_drawdown_pct: float
    exposure_pct: float
    trades: int
    passed: bool


def build_risk_report(result: BacktestResult, limits: RiskLimits) -> RiskReport:
    exposure_pct = _exposure_pct(result)
    trades = len(result.trades)
    notes: list[str] = []

    if result.max_drawdown_pct < limits.max_drawdown_pct:
        notes.append(
            f"drawdown {result.max_drawdown_pct:.2f}% breached limit {limits.max_drawdown_pct:.2f}%"
        )
    if trades < limits.min_trades:
        notes.append(f"only {trades} trades; minimum is {limits.min_trades}")
    if exposure_pct > limits.max_exposure_pct:
        notes.append(f"exposure {exposure_pct:.1f}% exceeded limit {limits.max_exposure_pct:.1f}%")

    return RiskReport(
        return_pct=result.return_pct,
        max_drawdown_pct=result.max_drawdown_pct,
        return_over_drawdown=_return_over_drawdown(result.return_pct, result.max_drawdown_pct),
        exposure_pct=exposure_pct,
        trades=trades,
        passed=not notes,
        notes=notes,
    )


def compare_position_sizes(
    candles: list[Candle],
    base_config: BacktestConfig,
    trade_fractions: list[float],
    limits: RiskLimits,
) -> list[PositionSizeResult]:
    rows: list[PositionSizeResult] = []

    # The signal depends only on closes, never on sizing: compute the decision
    # sequence once and replay the fills per trade fraction.
    sorted_candles = sorted(candles, key=lambda candle: candle.timestamp_ms)
    decisions = sma_wants_long(
        [candle.close for candle in sorted_candles],
        base_config.fast_window,
        base_config.slow_window,
    )

    for trade_fraction in trade_fractions:
        config = BacktestConfig(
            initial_cash=base_config.initial_cash,
            fast_window=base_config.fast_window,
            slow_window=base_config.slow_window,
            fee_rate=base_config.fee_rate,
            slippage_bps=base_config.slippage_bps,
            trade_fraction=trade_fraction,
        )
        result = replay_sma_decisions(sorted_candles, decisions, config)
        report = build_risk_report(result, limits)
        rows.append(
            PositionSizeResult(
                trade_fraction=trade_fraction,
                final_equity=result.final_equity,
                return_pct=result.return_pct,
                max_drawdown_pct=result.max_drawdown_pct,
                exposure_pct=report.exposure_pct,
                trades=report.trades,
                passed=report.passed,
            )
        )

    return rows


def _exposure_pct(result: BacktestResult) -> float:
    if not result.equity_curve:
        return 0.0

    exposed = sum(1 for point in result.equity_curve if point.asset > 0)
    return exposed / len(result.equity_curve) * 100


def _return_over_drawdown(return_pct: float, max_drawdown_pct: float) -> float:
    drawdown = abs(max_drawdown_pct)
    if drawdown == 0:
        return 0.0
    return return_pct / drawdown
