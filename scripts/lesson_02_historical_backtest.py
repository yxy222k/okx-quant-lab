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
from okx_quant_lab.okx_public import fetch_candles


def main() -> int:
    inst_id = "BTC-USDT"
    bar = "1H"
    candles = fetch_candles(inst_id, bar=bar, limit=200)
    config = BacktestConfig(
        initial_cash=1_000.0,
        fast_window=10,
        slow_window=30,
        fee_rate=0.001,
    )
    result = run_sma_backtest(candles, config)

    first_seen = _seen_at(candles[0].timestamp_ms)
    last_seen = _seen_at(candles[-1].timestamp_ms)

    print("OKX Lesson 02: historical candles + fee-aware SMA backtest")
    print(f"instrument:               {inst_id}")
    print(f"bar:                      {bar}")
    print(f"closed candles:           {len(candles)}")
    print(f"range_utc:                {first_seen} -> {last_seen}")
    print(f"initial_cash_usdt:        {config.initial_cash:.2f}")
    print(f"fee_rate:                 {config.fee_rate:.4%}")
    print(f"strategy:                 long when SMA({config.fast_window}) > SMA({config.slow_window})")
    print(f"trades:                   {len(result.trades)}")
    print(f"final_liquidation_equity: {result.final_equity:.2f} USDT")
    print(f"strategy_return:          {result.return_pct:.2f}%")
    print(f"buy_hold_return:          {result.buy_and_hold_return_pct:.2f}%")
    print(f"max_drawdown:             {result.max_drawdown_pct:.2f}%")

    if result.trades:
        print()
        print("last trades:")
        for trade in result.trades[-5:]:
            print(
                f"{_seen_at(trade.timestamp_ms)} "
                f"{trade.side:<4} price={trade.price:.2f} "
                f"qty={trade.quantity:.8f} fee={trade.fee:.4f}"
            )

    print()
    print("Lesson: a backtest is a question, not proof. Next we add slippage and save candles.")
    return 0


def _seen_at(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
