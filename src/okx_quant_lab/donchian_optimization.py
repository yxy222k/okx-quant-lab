from __future__ import annotations

from dataclasses import dataclass, replace

from okx_quant_lab.donchian_strategy import (
    DonchianBacktestConfig,
    run_donchian_breakout_backtest,
)
from okx_quant_lab.okx_public import Candle
from okx_quant_lab.walk_forward_core import rank_sweep_results


@dataclass(frozen=True)
class DonchianSweepResult:
    entry_window: int
    exit_window: int
    train_return_pct: float
    test_return_pct: float
    train_drawdown_pct: float
    test_drawdown_pct: float
    train_trades: int
    test_trades: int
    overfit_gap_pct: float


def sweep_donchian_parameters(
    train: list[Candle],
    test: list[Candle],
    entry_windows: list[int],
    exit_windows: list[int],
    base_config: DonchianBacktestConfig,
) -> list[DonchianSweepResult]:
    if not train or not test:
        raise ValueError("train and test segments must not be empty")

    results: list[DonchianSweepResult] = []
    shortest = min(len(train), len(test))

    for entry_window in entry_windows:
        for exit_window in exit_windows:
            if exit_window >= entry_window:
                continue
            if shortest <= entry_window + 1:
                continue

            config = replace(
                base_config,
                entry_window=entry_window,
                exit_window=exit_window,
            )
            train_result = run_donchian_breakout_backtest(train, config)
            test_result = run_donchian_breakout_backtest(test, config)

            results.append(
                DonchianSweepResult(
                    entry_window=entry_window,
                    exit_window=exit_window,
                    train_return_pct=train_result.return_pct,
                    test_return_pct=test_result.return_pct,
                    train_drawdown_pct=train_result.max_drawdown_pct,
                    test_drawdown_pct=test_result.max_drawdown_pct,
                    train_trades=len(train_result.trades),
                    test_trades=len(test_result.trades),
                    overfit_gap_pct=train_result.return_pct - test_result.return_pct,
                )
            )

    return rank_sweep_results(results)
