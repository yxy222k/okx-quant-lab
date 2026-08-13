#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.backtest import BacktestConfig
from okx_quant_lab.candle_store import load_candles_csv
from okx_quant_lab.portfolio import run_equal_weight_portfolio


def main() -> int:
    inst_ids = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT"]
    candle_map = {
        inst_id: load_candles_csv(ROOT / "data" / "candles" / f"{inst_id}_1H_scan.csv")
        for inst_id in inst_ids
    }
    config = BacktestConfig(
        initial_cash=1_000.0,
        fast_window=20,
        slow_window=50,
        fee_rate=0.001,
        slippage_bps=2.0,
        trade_fraction=0.5,
    )
    portfolio = run_equal_weight_portfolio(
        candle_map=candle_map,
        base_config=config,
        total_cash=1_000.0,
    )

    print("OKX Lesson 14: equal-weight portfolio simulation")
    print(f"markets:       {', '.join(inst_ids)}")
    print(f"strategy:      SMA({config.fast_window},{config.slow_window}), {config.trade_fraction:.0%} allocation per leg")
    print(f"final_equity:  {portfolio.final_equity:.2f} USDT")
    print(f"return:        {portfolio.return_pct:.2f}%")
    print(f"max_drawdown:  {portfolio.max_drawdown_pct:.2f}%")
    print(f"points:        {len(portfolio.equity_curve)}")
    print()
    print("legs:")
    print("symbol    return% drawdown% trades")
    for leg in portfolio.legs:
        result = leg.result
        print(
            f"{leg.inst_id:<9} "
            f"{result.return_pct:>7.2f} "
            f"{result.max_drawdown_pct:>9.2f} "
            f"{len(result.trades):>6}"
        )

    print()
    print("Lesson: diversification can smooth a curve, but it cannot rescue a weak signal by itself.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
