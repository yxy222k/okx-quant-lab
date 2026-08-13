from __future__ import annotations

from dataclasses import dataclass

from okx_quant_lab.backtest import BacktestConfig, run_sma_backtest
from okx_quant_lab.okx_public import Candle
from okx_quant_lab.walk_forward_core import rank_sweep_results


@dataclass(frozen=True)
class SplitCandles:
    train: list[Candle]
    test: list[Candle]


@dataclass(frozen=True)
class SweepResult:
    fast_window: int
    slow_window: int
    train_return_pct: float
    test_return_pct: float
    train_drawdown_pct: float
    test_drawdown_pct: float
    train_trades: int
    test_trades: int
    overfit_gap_pct: float


def train_test_split(candles: list[Candle], train_fraction: float = 0.7) -> SplitCandles:
    if not 0 < train_fraction < 1:
        raise ValueError("train_fraction must be between 0 and 1")
    if len(candles) < 2:
        raise ValueError("need at least two candles")

    sorted_candles = sorted(candles, key=lambda candle: candle.timestamp_ms)
    split_index = int(len(sorted_candles) * train_fraction)
    split_index = max(1, min(split_index, len(sorted_candles) - 1))

    return SplitCandles(
        train=sorted_candles[:split_index],
        test=sorted_candles[split_index:],
    )


def sweep_sma_parameters(
    train: list[Candle],
    test: list[Candle],
    fast_windows: list[int],
    slow_windows: list[int],
    base_config: BacktestConfig,
) -> list[SweepResult]:
    results: list[SweepResult] = []

    for fast_window in fast_windows:
        for slow_window in slow_windows:
            if fast_window >= slow_window:
                continue
            if len(train) <= slow_window or len(test) <= slow_window:
                continue

            config = BacktestConfig(
                initial_cash=base_config.initial_cash,
                fast_window=fast_window,
                slow_window=slow_window,
                fee_rate=base_config.fee_rate,
                slippage_bps=base_config.slippage_bps,
                trade_fraction=base_config.trade_fraction,
            )
            train_result = run_sma_backtest(train, config)
            test_result = run_sma_backtest(test, config)

            results.append(
                SweepResult(
                    fast_window=fast_window,
                    slow_window=slow_window,
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
