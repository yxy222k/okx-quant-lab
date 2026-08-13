from __future__ import annotations

from dataclasses import dataclass

from okx_quant_lab.grid_optimization import GridSweepResult, sweep_grid_parameters
from okx_quant_lab.okx_public import Candle
from okx_quant_lab.walk_forward_core import (
    split_walk_forward_windows,
    summarize_test_returns,
)


@dataclass(frozen=True)
class GridWalkForwardResult:
    window_index: int
    train_start_ms: int
    train_end_ms: int
    test_start_ms: int
    test_end_ms: int
    selected: GridSweepResult


@dataclass(frozen=True)
class GridWalkForwardSummary:
    windows: list[GridWalkForwardResult]
    average_test_return_pct: float
    median_test_return_pct: float
    cumulative_test_return_pct: float
    win_rate_pct: float


def walk_forward_grid(
    candles: list[Candle],
    train_size: int,
    test_size: int,
    step_size: int,
    range_pcts: list[float],
    grid_counts: list[int],
    initial_cash: float = 1_000.0,
    fee_rate: float = 0.001,
    slippage_bps: float = 0.0,
) -> GridWalkForwardSummary:
    windows: list[GridWalkForwardResult] = []
    for window in split_walk_forward_windows(candles, train_size, test_size, step_size):
        sweep = sweep_grid_parameters(
            train=window.train,
            test=window.test,
            range_pcts=range_pcts,
            grid_counts=grid_counts,
            initial_cash=initial_cash,
            fee_rate=fee_rate,
            slippage_bps=slippage_bps,
        )

        windows.append(
            GridWalkForwardResult(
                window_index=len(windows) + 1,
                train_start_ms=window.train[0].timestamp_ms,
                train_end_ms=window.train[-1].timestamp_ms,
                test_start_ms=window.test[0].timestamp_ms,
                test_end_ms=window.test[-1].timestamp_ms,
                selected=sweep[0],
            )
        )

    return summarize_grid_walk_forward(windows)


def summarize_grid_walk_forward(
    windows: list[GridWalkForwardResult],
) -> GridWalkForwardSummary:
    stats = summarize_test_returns(
        [window.selected.test_return_pct for window in windows]
    )
    return GridWalkForwardSummary(
        windows=windows,
        average_test_return_pct=stats.average_pct,
        median_test_return_pct=stats.median_pct,
        cumulative_test_return_pct=stats.cumulative_pct,
        win_rate_pct=stats.win_rate_pct,
    )
