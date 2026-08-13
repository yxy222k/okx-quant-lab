#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.backtest import BacktestConfig, run_sma_backtest
from okx_quant_lab.candle_store import load_candles_csv, save_candles_csv
from okx_quant_lab.okx_public import fetch_candles


def main() -> int:
    inst_id = "BTC-USDT"
    bar = "1H"
    output_path = ROOT / "data" / "candles" / f"{inst_id}_{bar}.csv"

    live_candles = fetch_candles(inst_id, bar=bar, limit=200)
    save_candles_csv(output_path, live_candles)
    candles = load_candles_csv(output_path)

    base_config = BacktestConfig(
        initial_cash=1_000.0,
        fast_window=10,
        slow_window=30,
        fee_rate=0.001,
        slippage_bps=0.0,
    )
    realistic_config = BacktestConfig(
        initial_cash=1_000.0,
        fast_window=10,
        slow_window=30,
        fee_rate=0.001,
        slippage_bps=2.0,
    )

    base = run_sma_backtest(candles, base_config)
    realistic = run_sma_backtest(candles, realistic_config)
    slippage_drag = realistic.return_pct - base.return_pct

    print("OKX Lesson 03: saved candles + slippage-aware backtest")
    print(f"instrument:               {inst_id}")
    print(f"bar:                      {bar}")
    print(f"saved_to:                 {output_path}")
    print(f"closed candles:           {len(candles)}")
    print(f"range_utc:                {_seen_at(candles[0].timestamp_ms)} -> {_seen_at(candles[-1].timestamp_ms)}")
    print(f"fee_rate:                 {realistic_config.fee_rate:.4%}")
    print(f"slippage_bps:             {realistic_config.slippage_bps:.2f}")
    print()
    print("comparison:")
    print(f"no_slippage_return:       {base.return_pct:.2f}%")
    print(f"with_slippage_return:     {realistic.return_pct:.2f}%")
    print(f"slippage_drag:            {slippage_drag:.2f} percentage points")
    print(f"with_slippage_equity:     {realistic.final_equity:.2f} USDT")
    print(f"with_slippage_drawdown:   {realistic.max_drawdown_pct:.2f}%")
    print(f"with_slippage_trades:     {len(realistic.trades)}")

    if realistic.trades:
        print()
        print("last trades with slipped fill prices:")
        for trade in realistic.trades[-5:]:
            print(
                f"{_seen_at(trade.timestamp_ms)} "
                f"{trade.side:<4} fill={trade.price:.2f} "
                f"qty={trade.quantity:.8f} fee={trade.fee:.4f}"
            )

    print()
    print("Lesson: a strategy that only works before slippage probably does not work.")
    return 0


def _seen_at(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
