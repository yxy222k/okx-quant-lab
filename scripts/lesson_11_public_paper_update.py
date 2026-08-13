#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.candle_store import load_candles_csv, merge_candles, save_candles_csv
from okx_quant_lab.okx_public import fetch_candles
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

    existing = load_candles_csv(candle_path) if candle_path.exists() else []
    latest = fetch_candles(inst_id, bar=bar, limit=200)
    candles = merge_candles(existing, latest)
    save_candles_csv(candle_path, candles)

    config = PaperConfig(inst_id=inst_id)
    state = load_paper_state(state_path) if state_path.exists() else new_paper_state(config)

    previous_last = state.last_timestamp_ms
    before_fills = len(state.fills)
    state = run_paper_session(candles, state, config)
    save_paper_state(state_path, state)

    new_candles = sum(1 for candle in candles if candle.timestamp_ms > previous_last)
    equity = paper_equity(state, candles[-1].close, config)

    print("OKX Lesson 11: public-data paper update loop")
    print(f"instrument:          {inst_id}")
    print(f"bar:                 {bar}")
    print(f"stored_candles:      {len(candles)}")
    print(f"latest_closed_utc:   {_seen_at(candles[-1].timestamp_ms)}")
    print(f"previous_state_utc:  {_seen_at(previous_last)}")
    print(f"processed_state_utc: {_seen_at(state.last_timestamp_ms)}")
    print(f"new_candles_seen:    {new_candles}")
    print(f"new_fills:           {len(state.fills) - before_fills}")
    print(f"cash:                {state.cash:.2f} USDT")
    print(f"asset:               {state.asset:.8f} {inst_id.split('-')[0]}")
    print(f"paper_equity:        {equity:.2f} USDT")
    print()
    print("Lesson: an update loop should be boring, resumable, and explicit about what changed.")
    return 0


def _seen_at(timestamp_ms: int) -> str:
    if timestamp_ms == 0:
        return "never"
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
