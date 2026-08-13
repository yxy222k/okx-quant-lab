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
from okx_quant_lab.grid_paper import (
    GridPaperConfig,
    grid_paper_equity,
    load_grid_paper_state,
    new_grid_paper_state,
    open_slot_count,
    run_grid_paper_session,
    save_grid_paper_state,
)
from okx_quant_lab.okx_public import fetch_historical_candles


def main() -> int:
    inst_id = "SOL-USDT"
    bar = "1H"
    candle_path = ROOT / "data" / "candles" / f"{inst_id}_{bar}_scan.csv"
    state_path = ROOT / "data" / "paper" / f"{inst_id}_{bar}_grid_state.json"

    if candle_path.exists():
        candles = load_candles_csv(candle_path)
    else:
        candles = fetch_historical_candles(inst_id, bar=bar, target_count=500)
        save_candles_csv(candle_path, candles)

    config = GridPaperConfig(
        inst_id=inst_id,
        range_pct=15.0,
        grid_count=10,
        initial_cash=1_000.0,
        fee_rate=0.001,
    )

    if state_path.exists():
        state = load_grid_paper_state(state_path)
    else:
        # The grid is anchored once, at deployment, on the first visible open.
        state = new_grid_paper_state(config, reference_price=candles[0].open)

    before_fills = len(state.fills)
    state = run_grid_paper_session(candles, state, config)
    save_grid_paper_state(state_path, state)

    mark_price = candles[-1].close
    equity = grid_paper_equity(state, mark_price, config)
    open_slots = open_slot_count(state)
    lower, upper = state.levels[0], state.levels[-1]

    print("OKX Lesson 21: local grid paper-trading replay")
    print(f"instrument:          {inst_id}")
    print(f"bar:                 {bar}")
    print(f"candles:             {len(candles)}")
    print(f"state_path:          {state_path}")
    print(f"grid_range:          {lower:.4f} .. {upper:.4f} ({config.grid_count} slots)")
    print(f"last_candle_utc:     {_seen_at(candles[-1].timestamp_ms)}")
    print(f"last_processed_utc:  {_seen_at(state.last_timestamp_ms)}")
    print(f"cash:                {state.cash:.2f} USDT")
    print(f"open_slots:          {open_slots} of {config.grid_count}")
    print(f"realized_profit:     {state.realized_profit:.2f} USDT")
    print(f"mark_price:          {mark_price:.4f}")
    print(f"paper_equity:        {equity:.2f} USDT")
    print(f"total_fills:         {len(state.fills)}")
    print(f"new_fills_this_run:  {len(state.fills) - before_fills}")

    if mark_price < lower:
        print()
        print(f"WARNING: mark price {mark_price:.4f} is below the grid range.")
        print("Every slot below is trapped and the grid cannot earn until price returns.")

    if state.fills:
        print()
        print("last fills:")
        for fill in state.fills[-5:]:
            print(
                f"{_seen_at(fill.timestamp_ms)} "
                f"{fill.side:<4} level={fill.level_index:>2} "
                f"fill={fill.price:.4f} qty={fill.quantity:.6f} fee={fill.fee:.4f}"
            )

    print()
    print("Lesson: a live grid is a promise to keep buying while price falls.")
    print("The state file remembers that promise between runs; make sure you do too.")
    return 0


def _seen_at(timestamp_ms: int) -> str:
    if timestamp_ms == 0:
        return "never"
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
