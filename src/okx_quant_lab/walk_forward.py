from __future__ import annotations

from dataclasses import dataclass

from okx_quant_lab.backtest import BacktestConfig
from okx_quant_lab.okx_public import Candle
from okx_quant_lab.optimization import SweepResult, sweep_sma_parameters
from okx_quant_lab.walk_forward_core import (
    split_walk_forward_windows,
    summarize_test_returns,
)


@dataclass(frozen=True)
class WalkForwardResult:
    window_index: int
    train_start_ms: int
    train_end_ms: int
    test_start_ms: int
    test_end_ms: int
    selected: SweepResult


@dataclass(frozen=True)
class WalkForwardSummary:
    windows: list[WalkForwardResult]
    average_test_return_pct: float
    median_test_return_pct: float
    cumulative_test_return_pct: float
    win_rate_pct: float


def walk_forward_sma(
    candles: list[Candle],
    train_size: int,
    test_size: int,
    step_size: int,
    fast_windows: list[int],
    slow_windows: list[int],
    base_config: BacktestConfig,
) -> WalkForwardSummary:
    windows: list[WalkForwardResult] = []
    for window in split_walk_forward_windows(candles, train_size, test_size, step_size):
        sweep = sweep_sma_parameters(
            train=window.train,
            test=window.test,
            fast_windows=fast_windows,
            slow_windows=slow_windows,
            base_config=base_config,
        )

        if sweep:
            windows.append(
                WalkForwardResult(
                    window_index=len(windows) + 1,
                    train_start_ms=window.train[0].timestamp_ms,
                    train_end_ms=window.train[-1].timestamp_ms,
                    test_start_ms=window.test[0].timestamp_ms,
                    test_end_ms=window.test[-1].timestamp_ms,
                    selected=sweep[0],
                )
            )

    return summarize_walk_forward(windows)


def summarize_walk_forward(windows: list[WalkForwardResult]) -> WalkForwardSummary:
    stats = summarize_test_returns(
        [window.selected.test_return_pct for window in windows]
    )
    return WalkForwardSummary(
        windows=windows,
        average_test_return_pct=stats.average_pct,
        median_test_return_pct=stats.median_pct,
        cumulative_test_return_pct=stats.cumulative_pct,
        win_rate_pct=stats.win_rate_pct,
    )
