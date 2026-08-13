#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.backtest import BacktestConfig, run_sma_backtest
from okx_quant_lab.candle_store import load_candles_csv
from okx_quant_lab.grid_strategy import grid_config_from_reference, run_grid_backtest


def main() -> int:
    inst_ids = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT"]
    sma_config = BacktestConfig(
        initial_cash=1_000.0,
        fast_window=20,
        slow_window=50,
        fee_rate=0.001,
        slippage_bps=2.0,
        trade_fraction=0.5,
    )

    print("OKX Lesson 18: grid trading vs trend following")
    print("Grid: +/-15% arithmetic range around the first open, 10 slots, maker fills.")
    print()
    print("symbol    grid% grid_dd% trips real$ unreal$ open below  sma%   bh%")

    for inst_id in inst_ids:
        path = ROOT / "data" / "candles" / f"{inst_id}_1H_scan.csv"
        candles = load_candles_csv(path)
        grid_config = grid_config_from_reference(
            reference_price=candles[0].open,
            range_pct=15.0,
            grid_count=10,
            initial_cash=1_000.0,
            fee_rate=0.001,
        )
        grid = run_grid_backtest(candles, grid_config)
        sma = run_sma_backtest(candles, sma_config)

        print(
            f"{inst_id:<9} "
            f"{grid.return_pct:>5.2f} "
            f"{grid.max_drawdown_pct:>8.2f} "
            f"{grid.round_trips:>5} "
            f"{grid.realized_profit:>5.1f} "
            f"{grid.unrealized_pnl:>7.1f} "
            f"{grid.open_slots:>4} "
            f"{grid.candles_below_range:>5} "
            f"{sma.return_pct:>5.2f} "
            f"{grid.buy_and_hold_return_pct:>5.2f}"
        )

    print()
    print("How to read this:")
    print("- real$ is banked grid profit; unreal$ is inventory still held, marked at the last close.")
    print("- open is how many grid slots are stuck holding coins bought higher up.")
    print("- below counts candles that closed under the grid range: the zone where a grid only bleeds.")
    print()
    print("Lesson: a grid converts volatility into income until the market trends;")
    print("then it converts your cash into inventory. Judge it by drawdown and")
    print("trapped inventory, never by realized profit alone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
