from __future__ import annotations

from dataclasses import dataclass

from okx_quant_lab.grid_strategy import grid_config_from_reference, run_grid_backtest
from okx_quant_lab.okx_public import Candle
from okx_quant_lab.walk_forward_core import rank_sweep_results


@dataclass(frozen=True)
class GridSweepResult:
    range_pct: float
    grid_count: int
    train_return_pct: float
    test_return_pct: float
    train_drawdown_pct: float
    test_drawdown_pct: float
    train_trips: int
    test_trips: int
    train_open_slots: int
    test_open_slots: int
    overfit_gap_pct: float


def sweep_grid_parameters(
    train: list[Candle],
    test: list[Candle],
    range_pcts: list[float],
    grid_counts: list[int],
    initial_cash: float = 1_000.0,
    fee_rate: float = 0.001,
    slippage_bps: float = 0.0,
) -> list[GridSweepResult]:
    if not train or not test:
        raise ValueError("train and test segments must not be empty")

    results: list[GridSweepResult] = []

    for range_pct in range_pcts:
        for grid_count in grid_counts:
            # A deployed grid can only be anchored at the price visible when it
            # starts, so each segment gets its own range around its first open.
            train_result = run_grid_backtest(
                train,
                grid_config_from_reference(
                    reference_price=train[0].open,
                    range_pct=range_pct,
                    grid_count=grid_count,
                    initial_cash=initial_cash,
                    fee_rate=fee_rate,
                    slippage_bps=slippage_bps,
                ),
            )
            test_result = run_grid_backtest(
                test,
                grid_config_from_reference(
                    reference_price=test[0].open,
                    range_pct=range_pct,
                    grid_count=grid_count,
                    initial_cash=initial_cash,
                    fee_rate=fee_rate,
                    slippage_bps=slippage_bps,
                ),
            )

            results.append(
                GridSweepResult(
                    range_pct=range_pct,
                    grid_count=grid_count,
                    train_return_pct=train_result.return_pct,
                    test_return_pct=test_result.return_pct,
                    train_drawdown_pct=train_result.max_drawdown_pct,
                    test_drawdown_pct=test_result.max_drawdown_pct,
                    train_trips=train_result.round_trips,
                    test_trips=test_result.round_trips,
                    train_open_slots=train_result.open_slots,
                    test_open_slots=test_result.open_slots,
                    overfit_gap_pct=train_result.return_pct - test_result.return_pct,
                )
            )

    return rank_sweep_results(results)
