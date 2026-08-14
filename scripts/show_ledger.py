#!/usr/bin/env python3
"""Human-readable view of the demo order ledgers."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.demo_execution import load_demo_order_ledger
from okx_quant_lab.demo_grid import load_demo_grid_state

LEDGERS = {
    "manual (lesson 27)": ROOT / "data" / "orders" / "demo_orders.json",
    "grid loop (retired 1H)": ROOT / "data" / "orders" / "demo_grid_orders.json",
    "grid BTC": ROOT / "data" / "orders" / "demo_grid_orders_BTC-USDT.json",
    "grid ETH": ROOT / "data" / "orders" / "demo_grid_orders_ETH-USDT.json",
    "grid SOL": ROOT / "data" / "orders" / "demo_grid_orders_SOL-USDT.json",
}
GRID_STATE_PATHS = sorted((ROOT / "data" / "demo").glob("*_demo_grid_state.json"))


def main() -> int:
    for title, path in LEDGERS.items():
        print(f"=== {title}: {path.name} ===")
        if not path.exists():
            print("  (no ledger yet)")
            print()
            continue

        records = load_demo_order_ledger(path)
        for record in records:
            request = record.request
            line = (
                f"  {_seen_at(request.created_at_ms)}  "
                f"{request.side:<4} {request.inst_id:<9} {record.status:<9}"
            )
            if record.fill_quantity:
                # PARTIAL moved the position too, so it needs the fill columns
                # just as much as FILLED — it is the case a human must chase.
                line += (
                    f" fill={record.fill_price:<10.4f} qty={record.fill_quantity:<11.6f} "
                    f"fee={record.fee:.6f} {record.fee_currency}"
                )
                if record.status != "FILLED":
                    line += f" {record.message}"
            else:
                line += f" {record.message}"
            print(line)
            print(f"      reason: {request.reason}")

        counts = Counter(record.status for record in records)
        fees = Counter()
        for record in records:
            if record.fee:
                fees[record.fee_currency] += record.fee
        print(f"  -- {len(records)} records: "
              + ", ".join(f"{status}={count}" for status, count in sorted(counts.items())))
        if fees:
            print("  -- total fees: "
                  + ", ".join(f"{total:.6f} {ccy}" for ccy, total in sorted(fees.items())))
        print()

    for path in GRID_STATE_PATHS:
        state = load_demo_grid_state(path)
        held = {i: qty for i, qty in enumerate(state.holdings) if qty > 0}
        print(f"=== grid state: {path.name} ===")
        print(f"  range:    {state.levels[0]:.4f} .. {state.levels[-1]:.4f}")
        print(f"  cash:     {state.cash:.2f} USDT   realized: {state.realized_profit:.2f} USDT")
        print(f"  holdings: {held if held else '(all slots empty)'}")
        print(f"  breaker:  {'TRIPPED' if state.breaker_tripped else 'ok'} "
              f"(day {state.day_utc or 'n/a'}, day-start equity {state.day_start_equity:.2f})")
        print(f"  last processed: {_seen_at(state.last_timestamp_ms)}")
        print()
    return 0


def _seen_at(timestamp_ms: int) -> str:
    if timestamp_ms == 0:
        return "never              "
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )


if __name__ == "__main__":
    raise SystemExit(main())
