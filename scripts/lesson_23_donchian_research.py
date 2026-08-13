#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.candle_store import load_candles_csv, save_candles_csv
from okx_quant_lab.donchian_optimization import sweep_donchian_parameters
from okx_quant_lab.donchian_strategy import (
    DonchianBacktestConfig,
    run_donchian_breakout_backtest,
)
from okx_quant_lab.donchian_walk_forward import walk_forward_donchian
from okx_quant_lab.okx_public import fetch_historical_candles
from okx_quant_lab.optimization import train_test_split


def main() -> int:
    base_config = DonchianBacktestConfig(
        initial_cash=1_000.0,
        entry_window=20,
        exit_window=10,
        fee_rate=0.001,
        slippage_bps=2.0,
        trade_fraction=0.5,
    )

    print("OKX Lesson 23: Donchian breakout research funnel")
    print()

    print("Stage 1: one configuration across the scan markets")
    print("symbol    donch% donch_dd% trades")
    for inst_id in ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT"]:
        path = ROOT / "data" / "candles" / f"{inst_id}_1H_scan.csv"
        candles = load_candles_csv(path)
        result = run_donchian_breakout_backtest(candles, base_config)
        print(
            f"{inst_id:<9} "
            f"{result.return_pct:>6.2f} "
            f"{result.max_drawdown_pct:>9.2f} "
            f"{len(result.trades):>6}"
        )

    deep_path = ROOT / "data" / "candles" / "BTC-USDT_1H_deep.csv"
    if deep_path.exists():
        candles = load_candles_csv(deep_path)
    else:
        candles = fetch_historical_candles("BTC-USDT", bar="1H", target_count=3_000)
        save_candles_csv(deep_path, candles)

    entry_windows = [10, 20, 30, 40, 55]
    exit_windows = [5, 10, 15, 20]

    print()
    print("Stage 2: train/test sweep on deep BTC-USDT data")
    split = train_test_split(candles, train_fraction=0.7)
    sweep = sweep_donchian_parameters(
        train=split.train,
        test=split.test,
        entry_windows=entry_windows,
        exit_windows=exit_windows,
        base_config=base_config,
    )
    print("entry exit train% test%  gap_pp train_dd% test_dd%")
    for result in sweep[:5]:
        print(
            f"{result.entry_window:>5} "
            f"{result.exit_window:>4} "
            f"{result.train_return_pct:>6.2f} "
            f"{result.test_return_pct:>6.2f} "
            f"{result.overfit_gap_pct:>6.2f} "
            f"{result.train_drawdown_pct:>9.2f} "
            f"{result.test_drawdown_pct:>8.2f}"
        )
    best_test = max(sweep, key=lambda result: result.test_return_pct)
    print(
        f"best_test_pair: donchian({best_test.entry_window},{best_test.exit_window}) "
        f"train={best_test.train_return_pct:.2f}% test={best_test.test_return_pct:.2f}%"
    )

    print()
    print("Stage 3: walk-forward on the same data")
    summary = walk_forward_donchian(
        candles,
        train_size=600,
        test_size=200,
        step_size=200,
        entry_windows=entry_windows,
        exit_windows=exit_windows,
        base_config=base_config,
    )
    print(f"windows:            {len(summary.windows)}")
    print(f"avg test return %:  {summary.average_test_return_pct:.2f}")
    print(f"median test ret %:  {summary.median_test_return_pct:.2f}")
    print(f"cumulative %:       {summary.cumulative_test_return_pct:.2f}")
    print(f"win rate %:         {summary.win_rate_pct:.2f}")

    print()
    print("Lesson: every new strategy family walks the same funnel -- one config")
    print("across markets, then a split sweep, then walk-forward. The funnel does")
    print("not make a strategy good; it stops a bad one from looking good.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
