from __future__ import annotations

from dataclasses import dataclass

from okx_quant_lab.donchian_optimization import (
    DonchianSweepResult,
    sweep_donchian_parameters,
)
from okx_quant_lab.donchian_strategy import DonchianBacktestConfig
from okx_quant_lab.okx_public import Candle
from okx_quant_lab.walk_forward_core import (
    split_walk_forward_windows,
    summarize_test_returns,
)


@dataclass(frozen=True)
class DonchianWalkForwardResult:
    window_index: int
    train_start_ms: int
    train_end_ms: int
    test_start_ms: int
    test_end_ms: int
    selected: DonchianSweepResult


@dataclass(frozen=True)
class DonchianWalkForwardSummary:
    windows: list[DonchianWalkForwardResult]
    average_test_return_pct: float
    median_test_return_pct: float
    cumulative_test_return_pct: float
    win_rate_pct: float


def walk_forward_donchian(
    candles: list[Candle],
    train_size: int,
    test_size: int,
    step_size: int,
    entry_windows: list[int],
    exit_windows: list[int],
    base_config: DonchianBacktestConfig,
) -> DonchianWalkForwardSummary:
    windows: list[DonchianWalkForwardResult] = []
    for window in split_walk_forward_windows(candles, train_size, test_size, step_size):
        sweep = sweep_donchian_parameters(
            train=window.train,
            test=window.test,
            entry_windows=entry_windows,
            exit_windows=exit_windows,
            base_config=base_config,
        )

        if sweep:
            windows.append(
                DonchianWalkForwardResult(
                    window_index=len(windows) + 1,
                    train_start_ms=window.train[0].timestamp_ms,
                    train_end_ms=window.train[-1].timestamp_ms,
                    test_start_ms=window.test[0].timestamp_ms,
                    test_end_ms=window.test[-1].timestamp_ms,
                    selected=sweep[0],
                )
            )

    return summarize_donchian_walk_forward(windows)


def summarize_donchian_walk_forward(
    windows: list[DonchianWalkForwardResult],
) -> DonchianWalkForwardSummary:
    stats = summarize_test_returns(
        [window.selected.test_return_pct for window in windows]
    )
    return DonchianWalkForwardSummary(
        windows=windows,
        average_test_return_pct=stats.average_pct,
        median_test_return_pct=stats.median_pct,
        cumulative_test_return_pct=stats.cumulative_pct,
        win_rate_pct=stats.win_rate_pct,
    )
