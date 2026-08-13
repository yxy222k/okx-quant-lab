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
from okx_quant_lab.rsi_strategy import RsiBacktestConfig, run_rsi_mean_reversion_backtest


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
    rsi_config = RsiBacktestConfig(
        initial_cash=1_000.0,
        rsi_period=14,
        buy_below=35.0,
        sell_above=55.0,
        fee_rate=0.001,
        slippage_bps=2.0,
        trade_fraction=0.5,
    )

    print("OKX Lesson 13: strategy family comparison")
    print("symbol    sma%  sma_dd% sma_tr rsi%  rsi_dd% rsi_tr")
    for inst_id in inst_ids:
        path = ROOT / "data" / "candles" / f"{inst_id}_1H_scan.csv"
        candles = load_candles_csv(path)
        sma = run_sma_backtest(candles, sma_config)
        rsi = run_rsi_mean_reversion_backtest(candles, rsi_config)
        print(
            f"{inst_id:<9} "
            f"{sma.return_pct:>5.2f} "
            f"{sma.max_drawdown_pct:>8.2f} "
            f"{len(sma.trades):>6} "
            f"{rsi.return_pct:>5.2f} "
            f"{rsi.max_drawdown_pct:>8.2f} "
            f"{len(rsi.trades):>6}"
        )

    print()
    print("Lesson: comparing strategy families is healthier than optimizing one idea until it confesses.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
