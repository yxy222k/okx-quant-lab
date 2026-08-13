#!/usr/bin/env python3
"""Retire an old demo grid deployment: sell any held inventory through the
demo executor (audited in the ledger) and archive the state file.

Usage:
  python3 scripts/retire_grid.py <state.json> <ledger.json> --confirm
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.demo_execution import (
    DemoExecutionLimits,
    DemoOrderExecutor,
    load_demo_order_ledger,
    quantize_to_lot,
    save_demo_order_ledger,
)
from okx_quant_lab.demo_grid import load_demo_grid_state
from okx_quant_lab.dry_run import OrderRequest
from okx_quant_lab.okx_demo_private import load_demo_credentials
from okx_quant_lab.okx_public import fetch_instrument_spec, fetch_ticker


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state_path", type=Path)
    parser.add_argument("ledger_path", type=Path)
    parser.add_argument("--inst-id", default="SOL-USDT")
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()

    state = load_demo_grid_state(args.state_path)
    total_held = sum(state.holdings)
    print(f"retiring grid state: {args.state_path}")
    print(f"held inventory: {total_held:.8f} {args.inst_id.split('-')[0]}")

    if total_held > 0:
        credentials = load_demo_credentials()
        spec = fetch_instrument_spec(args.inst_id)
        mark = fetch_ticker(args.inst_id).last
        quantity = quantize_to_lot(total_held, spec.lot_size)
        if quantity < spec.min_size:
            print(f"inventory below min size {spec.min_size}; leaving as dust")
        else:
            records = (
                load_demo_order_ledger(args.ledger_path)
                if args.ledger_path.exists()
                else []
            )
            executor = DemoOrderExecutor(
                credentials, DemoExecutionLimits(max_order_usdt=25.0), records=records
            )
            record = executor.submit(
                OrderRequest(
                    client_order_id=f"retire:{args.inst_id}:{int(time.time() * 1000)}:SELL",
                    inst_id=args.inst_id,
                    side="SELL",
                    quote_amount_usdt=0.0,
                    base_quantity=quantity,
                    reference_price=mark,
                    created_at_ms=int(time.time() * 1000),
                    reason="grid retirement: liquidate before redeployment",
                ),
                confirmed=args.confirm,
            )
            save_demo_order_ledger(args.ledger_path, executor.records)
            print(f"liquidation: {record.status} {record.message}")
            if record.status == "FILLED":
                print(f"  fill={record.fill_price:.4f} qty={record.fill_quantity:.6f}")

    # Timestamped so a rerun can never silently clobber an earlier archive
    # (POSIX rename overwrites an existing target without complaint).
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = args.state_path.with_name(f"{args.state_path.name}.retired.{stamp}")
    args.state_path.rename(archive)
    print(f"state archived to: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
