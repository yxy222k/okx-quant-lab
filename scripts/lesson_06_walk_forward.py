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
from okx_quant_lab.walk_forward import walk_forward_sma


def main() -> int:
    candle_path = ROOT / "data" / "candles" / "BTC-USDT_1H_history.csv"
    if not candle_path.exists():
        raise SystemExit(
            f"Missing {candle_path}. Run scripts/lesson_05_collect_history.py first."
        )

    candles = load_candles_csv(candle_path)
    base_config = BacktestConfig(
        initial_cash=1_000.0,
        fee_rate=0.001,
        slippage_bps=2.0,
    )
    summary = walk_forward_sma(
        candles=candles,
        train_size=360,
        test_size=120,
        step_size=120,
        fast_windows=[5, 8, 10, 12, 15, 20],
        slow_windows=[20, 25, 30, 40, 50, 80],
        base_config=base_config,
    )

    print("OKX Lesson 06: walk-forward SMA validation")
    print(f"source:                 {candle_path}")
    print(f"candles:                {len(candles)}")
    print(f"range_utc:              {_seen_at(candles[0].timestamp_ms)} -> {_seen_at(candles[-1].timestamp_ms)}")
    print(f"train/test/step:        360 / 120 / 120 candles")
    print(f"fee_rate:               {base_config.fee_rate:.4%}")
    print(f"slippage_bps:           {base_config.slippage_bps:.2f}")
    print(f"windows:                {len(summary.windows)}")
    print(f"avg_test_return:        {summary.average_test_return_pct:.2f}%")
    print(f"median_test_return:     {summary.median_test_return_pct:.2f}%")
    print(f"cumulative_test_return: {summary.cumulative_test_return_pct:.2f}%")
    print(f"win_rate:               {summary.win_rate_pct:.1f}%")
    print()
    print("window selected train%  test%   gap_pp test_dd% trades test_range")
    for window in summary.windows:
        selected = window.selected
        test_range = f"{_date(window.test_start_ms)}->{_date(window.test_end_ms)}"
        print(
            f"{window.window_index:>6} "
            f"{selected.fast_window:>3}/{selected.slow_window:<3} "
            f"{selected.train_return_pct:>6.2f} "
            f"{selected.test_return_pct:>7.2f} "
            f"{selected.overfit_gap_pct:>7.2f} "
            f"{selected.test_drawdown_pct:>8.2f} "
            f"{selected.test_trades:>6} "
            f"{test_range}"
        )

    print()
    print("Lesson: robust parameters survive repeated test windows; lucky ones decay fast.")
    return 0


def _seen_at(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


def _date(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).date().isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
