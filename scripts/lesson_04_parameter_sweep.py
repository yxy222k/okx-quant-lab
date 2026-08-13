#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.backtest import BacktestConfig
from okx_quant_lab.candle_store import load_candles_csv
from okx_quant_lab.optimization import sweep_sma_parameters, train_test_split


def main() -> int:
    candle_path = ROOT / "data" / "candles" / "BTC-USDT_1H.csv"
    if not candle_path.exists():
        raise SystemExit(
            f"Missing {candle_path}. Run scripts/lesson_03_slippage_and_storage.py first."
        )

    candles = load_candles_csv(candle_path)
    split = train_test_split(candles, train_fraction=0.7)
    base_config = BacktestConfig(
        initial_cash=1_000.0,
        fee_rate=0.001,
        slippage_bps=2.0,
    )
    results = sweep_sma_parameters(
        train=split.train,
        test=split.test,
        fast_windows=[5, 8, 10, 12, 15, 20],
        slow_windows=[20, 25, 30, 40, 50],
        base_config=base_config,
    )

    print("OKX Lesson 04: SMA parameter sweep + train/test split")
    print(f"source:          {candle_path}")
    print(f"candles:         {len(candles)}")
    print(f"train_range_utc: {_seen_at(split.train[0].timestamp_ms)} -> {_seen_at(split.train[-1].timestamp_ms)}")
    print(f"test_range_utc:  {_seen_at(split.test[0].timestamp_ms)} -> {_seen_at(split.test[-1].timestamp_ms)}")
    print(f"fee_rate:        {base_config.fee_rate:.4%}")
    print(f"slippage_bps:    {base_config.slippage_bps:.2f}")
    print()

    if not results:
        raise SystemExit("No parameter pairs had enough train and test candles.")

    print("top by training return:")
    _print_table(results[:10])

    best_train = results[0]
    best_test = max(results, key=lambda result: result.test_return_pct)

    print()
    print("sanity check:")
    print(
        "best_train_pair: "
        f"SMA({best_train.fast_window},{best_train.slow_window}) "
        f"train={best_train.train_return_pct:.2f}% "
        f"test={best_train.test_return_pct:.2f}% "
        f"gap={best_train.overfit_gap_pct:.2f} pp"
    )
    print(
        "best_test_pair:  "
        f"SMA({best_test.fast_window},{best_test.slow_window}) "
        f"train={best_test.train_return_pct:.2f}% "
        f"test={best_test.test_return_pct:.2f}% "
        f"gap={best_test.overfit_gap_pct:.2f} pp"
    )

    print()
    print("Lesson: choose parameters by robustness, not by the prettiest training score.")
    return 0


def _print_table(results: list) -> None:
    print("fast slow train%  test%   gap_pp  train_dd% test_dd% trades")
    for result in results:
        trades = f"{result.train_trades}/{result.test_trades}"
        print(
            f"{result.fast_window:>4} "
            f"{result.slow_window:>4} "
            f"{result.train_return_pct:>6.2f} "
            f"{result.test_return_pct:>7.2f} "
            f"{result.overfit_gap_pct:>7.2f} "
            f"{result.train_drawdown_pct:>9.2f} "
            f"{result.test_drawdown_pct:>8.2f} "
            f"{trades:>6}"
        )


def _seen_at(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
