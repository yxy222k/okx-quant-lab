from __future__ import annotations

from dataclasses import dataclass

from okx_quant_lab.donchian_optimization import (
    DonchianSweepResult,
    sweep_donchian_parameters,
)
from okx_quant_lab.donchian_strategy import DonchianBacktestConfig
from okx_quant_lab.okx_public import Candle


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
    _validate_inputs(candles, train_size, test_size, step_size)

    sorted_candles = sorted(candles, key=lambda candle: candle.timestamp_ms)
    windows: list[DonchianWalkForwardResult] = []
    start = 0

    while start + train_size + test_size <= len(sorted_candles):
        train = sorted_candles[start : start + train_size]
        test = sorted_candles[start + train_size : start + train_size + test_size]
        sweep = sweep_donchian_parameters(
            train=train,
            test=test,
            entry_windows=entry_windows,
            exit_windows=exit_windows,
            base_config=base_config,
        )

        if sweep:
            windows.append(
                DonchianWalkForwardResult(
                    window_index=len(windows) + 1,
                    train_start_ms=train[0].timestamp_ms,
                    train_end_ms=train[-1].timestamp_ms,
                    test_start_ms=test[0].timestamp_ms,
                    test_end_ms=test[-1].timestamp_ms,
                    selected=sweep[0],
                )
            )

        start += step_size

    return summarize_donchian_walk_forward(windows)


def summarize_donchian_walk_forward(
    windows: list[DonchianWalkForwardResult],
) -> DonchianWalkForwardSummary:
    test_returns = [window.selected.test_return_pct for window in windows]
    if not test_returns:
        return DonchianWalkForwardSummary(
            windows=windows,
            average_test_return_pct=0.0,
            median_test_return_pct=0.0,
            cumulative_test_return_pct=0.0,
            win_rate_pct=0.0,
        )

    sorted_returns = sorted(test_returns)
    midpoint = len(sorted_returns) // 2
    if len(sorted_returns) % 2 == 1:
        median = sorted_returns[midpoint]
    else:
        median = (sorted_returns[midpoint - 1] + sorted_returns[midpoint]) / 2

    cumulative_multiplier = 1.0
    for value in test_returns:
        cumulative_multiplier *= 1 + value / 100

    wins = sum(1 for value in test_returns if value > 0)

    return DonchianWalkForwardSummary(
        windows=windows,
        average_test_return_pct=sum(test_returns) / len(test_returns),
        median_test_return_pct=median,
        cumulative_test_return_pct=(cumulative_multiplier - 1) * 100,
        win_rate_pct=wins / len(test_returns) * 100,
    )


def _validate_inputs(
    candles: list[Candle],
    train_size: int,
    test_size: int,
    step_size: int,
) -> None:
    if train_size <= 0:
        raise ValueError("train_size must be positive")
    if test_size <= 0:
        raise ValueError("test_size must be positive")
    if step_size <= 0:
        raise ValueError("step_size must be positive")
    if len(candles) < train_size + test_size:
        raise ValueError("not enough candles for one walk-forward window")
