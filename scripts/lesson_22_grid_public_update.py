#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.candle_store import load_candles_csv, merge_candles, save_candles_csv
from okx_quant_lab.grid_paper import (
    GridPaperConfig,
    load_grid_paper_state,
    new_grid_paper_state,
    run_grid_paper_session,
    save_grid_paper_state,
)
from okx_quant_lab.monitoring import (
    build_grid_paper_status,
    check_candle_freshness,
    check_grid_price_in_range,
    check_grid_state_caught_up,
    render_grid_markdown_report,
)
from okx_quant_lab.okx_public import fetch_candles


def main() -> int:
    inst_id = "SOL-USDT"
    bar = "1H"
    candle_path = ROOT / "data" / "candles" / f"{inst_id}_{bar}_scan.csv"
    state_path = ROOT / "data" / "paper" / f"{inst_id}_{bar}_grid_state.json"
    report_path = ROOT / "reports" / "lesson_22_grid_monitoring.md"

    existing = load_candles_csv(candle_path) if candle_path.exists() else []
    latest = fetch_candles(inst_id, bar=bar, limit=200)
    candles = merge_candles(existing, latest)
    save_candles_csv(candle_path, candles)

    config = GridPaperConfig(inst_id=inst_id)
    if state_path.exists():
        state = load_grid_paper_state(state_path)
    else:
        state = new_grid_paper_state(config, reference_price=candles[0].open)

    previous_last = state.last_timestamp_ms
    before_fills = len(state.fills)
    state = run_grid_paper_session(candles, state, config)
    save_grid_paper_state(state_path, state)

    now_ms = int(time.time() * 1000)
    checks = [
        check_candle_freshness(inst_id, candles, now_ms, max_age_hours=2.0),
        check_grid_state_caught_up(state, candles),
        check_grid_price_in_range(state, candles),
    ]
    status = build_grid_paper_status(inst_id, state, candles, config)
    report = render_grid_markdown_report(
        title="Grid Paper Monitoring Report",
        generated_at_ms=now_ms,
        checks=checks,
        grid_status=status,
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    new_candles = sum(1 for candle in candles if candle.timestamp_ms > previous_last)

    print("OKX Lesson 22: public-data grid update loop")
    print(f"instrument:          {inst_id}")
    print(f"bar:                 {bar}")
    print(f"stored_candles:      {len(candles)}")
    print(f"latest_closed_utc:   {_seen_at(candles[-1].timestamp_ms)}")
    print(f"previous_state_utc:  {_seen_at(previous_last)}")
    print(f"processed_state_utc: {_seen_at(state.last_timestamp_ms)}")
    print(f"new_candles_seen:    {new_candles}")
    print(f"new_fills:           {len(state.fills) - before_fills}")
    print(f"cash:                {state.cash:.2f} USDT")
    print(f"open_slots:          {status.open_slots} of {status.grid_count}")
    print(f"realized_profit:     {state.realized_profit:.2f} USDT")
    print(f"paper_equity:        {status.equity:.2f} USDT")
    print(f"report:              {report_path}")
    print()
    for check in checks:
        flag = "PASS" if check.passed else "FAIL"
        print(f"[{flag}] {check.name}: {check.message}")
    print()
    print("Lesson: a grid update loop needs one extra alarm the SMA loop does not --")
    print("has price left the range? Below the range, the grid is not a strategy")
    print("anymore, just a bag of inventory waiting.")
    return 0


def _seen_at(timestamp_ms: int) -> str:
    if timestamp_ms == 0:
        return "never"
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
