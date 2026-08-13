from __future__ import annotations

from dataclasses import dataclass

from okx_quant_lab.backtest import BacktestConfig, run_sma_backtest
from okx_quant_lab.okx_public import Candle
from okx_quant_lab.risk import RiskLimits, build_risk_report


@dataclass(frozen=True)
class SymbolScanResult:
    inst_id: str
    candles: int
    return_pct: float
    buy_hold_return_pct: float
    max_drawdown_pct: float
    exposure_pct: float
    trades: int
    passed: bool


def scan_symbols(
    candle_map: dict[str, list[Candle]],
    config: BacktestConfig,
    limits: RiskLimits,
) -> list[SymbolScanResult]:
    rows: list[SymbolScanResult] = []

    for inst_id, candles in sorted(candle_map.items()):
        result = run_sma_backtest(candles, config)
        report = build_risk_report(result, limits)
        rows.append(
            SymbolScanResult(
                inst_id=inst_id,
                candles=len(candles),
                return_pct=result.return_pct,
                buy_hold_return_pct=result.buy_and_hold_return_pct,
                max_drawdown_pct=result.max_drawdown_pct,
                exposure_pct=report.exposure_pct,
                trades=report.trades,
                passed=report.passed,
            )
        )

    return sorted(rows, key=lambda row: row.return_pct, reverse=True)
