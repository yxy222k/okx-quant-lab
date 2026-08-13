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
from okx_quant_lab.donchian_paper import (
    DonchianPaperConfig,
    donchian_paper_equity,
    load_paper_state,
    new_donchian_paper_state,
    run_donchian_paper_session,
    save_paper_state,
)
from okx_quant_lab.monitoring import (
    check_candle_freshness,
    check_paper_state_caught_up,
    render_markdown_report,
    PaperStatus,
)
from okx_quant_lab.okx_public import fetch_candles


def main() -> int:
    inst_id = "ETH-USDT"
    bar = "1H"
    candle_path = ROOT / "data" / "candles" / f"{inst_id}_{bar}_scan.csv"
    state_path = ROOT / "data" / "paper" / f"{inst_id}_{bar}_donchian_state.json"
    report_path = ROOT / "reports" / "lesson_24_donchian_monitoring.md"

    existing = load_candles_csv(candle_path) if candle_path.exists() else []
    latest = fetch_candles(inst_id, bar=bar, limit=200)
    candles = merge_candles(existing, latest)
    save_candles_csv(candle_path, candles)

    config = DonchianPaperConfig(inst_id=inst_id)
    if state_path.exists():
        state = load_paper_state(state_path)
    else:
        state = new_donchian_paper_state(config)

    previous_last = state.last_timestamp_ms
    before_fills = len(state.fills)
    state = run_donchian_paper_session(candles, state, config)
    save_paper_state(state_path, state)

    mark_price = candles[-1].close
    equity = donchian_paper_equity(state, mark_price, config)
    now_ms = int(time.time() * 1000)
    checks = [
        check_candle_freshness(inst_id, candles, now_ms, max_age_hours=2.0),
        check_paper_state_caught_up(state, candles),
    ]
    status = PaperStatus(
        inst_id=inst_id,
        cash=state.cash,
        asset=state.asset,
        mark_price=mark_price,
        equity=equity,
        fills=len(state.fills),
        last_processed_ms=state.last_timestamp_ms,
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_markdown_report(
            title="Donchian Paper Monitoring Report",
            generated_at_ms=now_ms,
            checks=checks,
            paper_status=status,
        ),
        encoding="utf-8",
    )

    new_candles = sum(1 for candle in candles if candle.timestamp_ms > previous_last)

    print("OKX Lesson 24: Donchian paper update loop")
    print(f"instrument:          {inst_id}")
    print(f"bar:                 {bar}")
    print(f"strategy:            donchian({config.entry_window},{config.exit_window})")
    print(f"stored_candles:      {len(candles)}")
    print(f"latest_closed_utc:   {_seen_at(candles[-1].timestamp_ms)}")
    print(f"previous_state_utc:  {_seen_at(previous_last)}")
    print(f"processed_state_utc: {_seen_at(state.last_timestamp_ms)}")
    print(f"new_candles_seen:    {new_candles}")
    print(f"new_fills:           {len(state.fills) - before_fills}")
    print(f"cash:                {state.cash:.2f} USDT")
    print(f"asset:               {state.asset:.8f} {inst_id.split('-')[0]}")
    print(f"paper_equity:        {equity:.2f} USDT")
    print(f"report:              {report_path}")
    print()
    for check in checks:
        flag = "PASS" if check.passed else "FAIL"
        print(f"[{flag}] {check.name}: {check.message}")
    print()
    print("Lesson: the research funnel rejected this family on BTC; the paper loop")
    print("exists to keep collecting evidence cheaply, not to sneak it into service.")
    return 0


def _seen_at(timestamp_ms: int) -> str:
    if timestamp_ms == 0:
        return "never"
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
