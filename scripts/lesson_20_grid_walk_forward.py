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
from okx_quant_lab.candle_store import refresh_candles
from okx_quant_lab.grid_walk_forward import walk_forward_grid
from okx_quant_lab.okx_public import Candle
from okx_quant_lab.walk_forward import walk_forward_sma


def main() -> int:
    inst_id = "BTC-USDT"
    bar = "1H"
    target_count = 3_000
    deep_path = ROOT / "data" / "candles" / f"{inst_id}_{bar}_deep.csv"
    candles = _load_or_fetch_deep_candles(inst_id, bar, target_count, deep_path)

    train_size, test_size, step_size = 600, 200, 200

    print("OKX Lesson 20: walk-forward grid versus walk-forward SMA")
    print(f"instrument: {inst_id}  candles: {len(candles)}")
    print(f"windows: train={train_size} test={test_size} step={step_size}")
    print("grid fills as maker (0 bps); SMA fills as taker (2 bps).")
    print()

    grid_summary = walk_forward_grid(
        candles,
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
        range_pcts=[5.0, 10.0, 15.0, 20.0, 30.0],
        grid_counts=[5, 10, 20, 40],
        initial_cash=1_000.0,
        fee_rate=0.001,
    )
    sma_summary = walk_forward_sma(
        candles,
        train_size=train_size,
        test_size=test_size,
        step_size=step_size,
        fast_windows=[5, 8, 10, 12, 15, 20],
        slow_windows=[20, 30, 40, 50, 60, 80],
        base_config=BacktestConfig(
            initial_cash=1_000.0,
            fee_rate=0.001,
            slippage_bps=2.0,
        ),
    )

    print("grid windows (parameters picked on train, scored on unseen test):")
    print("window selected      train%  test%  te_open test_range")
    for window in grid_summary.windows:
        selected = window.selected
        print(
            f"{window.window_index:>6} "
            f"{selected.range_pct:>4.0f}%/{selected.grid_count:<7} "
            f"{selected.train_return_pct:>6.2f} "
            f"{selected.test_return_pct:>6.2f} "
            f"{selected.test_open_slots:>7} "
            f"{_utc_date(window.test_start_ms)}->{_utc_date(window.test_end_ms)}"
        )

    print()
    print("summary                 grid     sma")
    print(f"windows           {len(grid_summary.windows):>8} {len(sma_summary.windows):>7}")
    print(
        f"avg test return % {grid_summary.average_test_return_pct:>8.2f} "
        f"{sma_summary.average_test_return_pct:>7.2f}"
    )
    print(
        f"median test ret % {grid_summary.median_test_return_pct:>8.2f} "
        f"{sma_summary.median_test_return_pct:>7.2f}"
    )
    print(
        f"cumulative %      {grid_summary.cumulative_test_return_pct:>8.2f} "
        f"{sma_summary.cumulative_test_return_pct:>7.2f}"
    )
    print(
        f"win rate %        {grid_summary.win_rate_pct:>8.2f} "
        f"{sma_summary.win_rate_pct:>7.2f}"
    )

    print()
    print("Lesson: walk-forward asks each strategy the same hard question --")
    print("would yesterday's chosen parameters have survived tomorrow? Compare")
    print("the cumulative rows, then remember neither includes funding for the")
    print("months when the strategy sat in trapped inventory.")
    return 0


def _load_or_fetch_deep_candles(
    inst_id: str,
    bar: str,
    target_count: int,
    path: Path,
) -> list[Candle]:
    candles = refresh_candles(path, inst_id, bar=bar, target_count=target_count)
    print(f"refreshed {len(candles)} candles in {path}")
    return candles


def _utc_date(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).date().isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
