#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.candle_store import refresh_candles
from okx_quant_lab.grid_optimization import GridSweepResult, sweep_grid_parameters
from okx_quant_lab.okx_public import Candle
from okx_quant_lab.optimization import train_test_split


def main() -> int:
    inst_id = "BTC-USDT"
    bar = "1H"
    target_count = 3_000
    deep_path = ROOT / "data" / "candles" / f"{inst_id}_{bar}_deep.csv"

    candles = _load_or_fetch_deep_candles(inst_id, bar, target_count, deep_path)
    split = train_test_split(candles, train_fraction=0.7)

    print("OKX Lesson 19: grid parameter sweep with train/test split")
    print(f"instrument: {inst_id}  candles: {len(candles)}")
    print(f"train: {len(split.train)} candles ending {_utc(split.train[-1].timestamp_ms)}")
    print(f"test:  {len(split.test)} candles ending {_utc(split.test[-1].timestamp_ms)}")
    print()

    results = sweep_grid_parameters(
        train=split.train,
        test=split.test,
        range_pcts=[5.0, 10.0, 15.0, 20.0, 30.0],
        grid_counts=[5, 10, 20, 40],
        initial_cash=1_000.0,
        fee_rate=0.001,
    )

    print("range% grids train% test%  gap_pp train_dd% test_dd% tr_trips te_trips te_open")
    for result in results:
        print(_format_row(result))

    best_train = results[0]
    best_test = max(results, key=lambda result: result.test_return_pct)
    print()
    print("sanity check:")
    print(
        f"best_train_pair: grid({best_train.range_pct:g}%, {best_train.grid_count}) "
        f"train={best_train.train_return_pct:.2f}% test={best_train.test_return_pct:.2f}% "
        f"gap={best_train.overfit_gap_pct:.2f} pp"
    )
    print(
        f"best_test_pair:  grid({best_test.range_pct:g}%, {best_test.grid_count}) "
        f"train={best_test.train_return_pct:.2f}% test={best_test.test_return_pct:.2f}% "
        f"gap={best_test.overfit_gap_pct:.2f} pp"
    )
    print()
    print("Lesson: a grid's backtest quality is mostly a bet on the range holding.")
    print("If the winning range on train data loses on test data, the edge was the")
    print("period, not the parameters.")
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


def _format_row(result: GridSweepResult) -> str:
    return (
        f"{result.range_pct:>6.1f} "
        f"{result.grid_count:>5} "
        f"{result.train_return_pct:>6.2f} "
        f"{result.test_return_pct:>6.2f} "
        f"{result.overfit_gap_pct:>6.2f} "
        f"{result.train_drawdown_pct:>9.2f} "
        f"{result.test_drawdown_pct:>8.2f} "
        f"{result.train_trips:>8} "
        f"{result.test_trips:>8} "
        f"{result.test_open_slots:>7}"
    )


def _utc(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
