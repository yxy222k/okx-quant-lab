from __future__ import annotations

from dataclasses import dataclass

from okx_quant_lab.okx_public import Candle


@dataclass(frozen=True)
class WalkForwardWindow:
    train: list[Candle]
    test: list[Candle]


@dataclass(frozen=True)
class TestReturnStats:
    average_pct: float
    median_pct: float
    cumulative_pct: float
    win_rate_pct: float


def split_walk_forward_windows(
    candles: list[Candle],
    train_size: int,
    test_size: int,
    step_size: int,
) -> list[WalkForwardWindow]:
    """Chronological rolling train/test splits shared by every strategy family."""
    validate_walk_forward_inputs(candles, train_size, test_size, step_size)

    sorted_candles = sorted(candles, key=lambda candle: candle.timestamp_ms)
    windows: list[WalkForwardWindow] = []
    start = 0

    while start + train_size + test_size <= len(sorted_candles):
        windows.append(
            WalkForwardWindow(
                train=sorted_candles[start : start + train_size],
                test=sorted_candles[start + train_size : start + train_size + test_size],
            )
        )
        start += step_size

    return windows


def summarize_test_returns(test_returns: list[float]) -> TestReturnStats:
    if not test_returns:
        return TestReturnStats(
            average_pct=0.0, median_pct=0.0, cumulative_pct=0.0, win_rate_pct=0.0
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

    return TestReturnStats(
        average_pct=sum(test_returns) / len(test_returns),
        median_pct=median,
        cumulative_pct=(cumulative_multiplier - 1) * 100,
        win_rate_pct=wins / len(test_returns) * 100,
    )


def validate_walk_forward_inputs(
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


def rank_sweep_results(results: list) -> list:
    """Shared sweep ranking: train return, then test return, then overfit gap.

    Any result type with train_return_pct / test_return_pct / overfit_gap_pct
    fields works (SweepResult, GridSweepResult, DonchianSweepResult).
    """
    return sorted(
        results,
        key=lambda result: (
            result.train_return_pct,
            result.test_return_pct,
            -abs(result.overfit_gap_pct),
        ),
        reverse=True,
    )
