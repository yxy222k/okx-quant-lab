#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.candle_store import load_candles_csv, save_candles_csv
from okx_quant_lab.okx_public import fetch_historical_candles
from okx_quant_lab.paper import (
    PaperConfig,
    load_paper_state,
    new_paper_state,
    paper_equity,
    run_paper_session,
    save_paper_state,
)


def main() -> int:
    inst_id = "SOL-USDT"
    bar = "1H"
    candle_path = ROOT / "data" / "candles" / f"{inst_id}_{bar}_scan.csv"
    state_path = ROOT / "data" / "paper" / f"{inst_id}_{bar}_state.json"

    if candle_path.exists():
        candles = load_candles_csv(candle_path)
    else:
        candles = fetch_historical_candles(inst_id, bar=bar, target_count=500)
        save_candles_csv(candle_path, candles)

    config = PaperConfig(
        inst_id=inst_id,
        initial_cash=1_000.0,
        fast_window=20,
        slow_window=50,
        fee_rate=0.001,
        slippage_bps=2.0,
        trade_fraction=0.5,
    )

    if state_path.exists():
        state = load_paper_state(state_path)
    else:
        state = new_paper_state(config)

    before_fills = len(state.fills)
    state = run_paper_session(candles, state, config)
    save_paper_state(state_path, state)

    mark_price = candles[-1].close
    equity = paper_equity(state, mark_price, config)

    print("OKX Lesson 09: local paper-trading replay")
    print(f"instrument:          {inst_id}")
    print(f"bar:                 {bar}")
    print(f"candles:             {len(candles)}")
    print(f"state_path:          {state_path}")
    print(f"last_candle_utc:     {_seen_at(candles[-1].timestamp_ms)}")
    print(f"last_processed_utc:  {_seen_at(state.last_timestamp_ms)}")
    print(f"cash:                {state.cash:.2f} USDT")
    print(f"asset:               {state.asset:.8f} {inst_id.split('-')[0]}")
    print(f"mark_price:          {mark_price:.4f}")
    print(f"paper_equity:        {equity:.2f} USDT")
    print(f"total_fills:         {len(state.fills)}")
    print(f"new_fills_this_run:  {len(state.fills) - before_fills}")

    if state.fills:
        print()
        print("last fills:")
        for fill in state.fills[-5:]:
            print(
                f"{_seen_at(fill.timestamp_ms)} "
                f"{fill.side:<4} fill={fill.price:.4f} "
                f"qty={fill.quantity:.6f} fee={fill.fee:.4f}"
            )

    print()
    print("Lesson: paper trading is a state machine. If it cannot resume safely, it is not ready.")
    return 0


def _seen_at(timestamp_ms: int) -> str:
    if timestamp_ms == 0:
        return "never"
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
