#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
from okx_quant_lab.dry_run import OrderRequest
from okx_quant_lab.okx_demo_private import fetch_demo_balance, load_demo_credentials
from okx_quant_lab.okx_public import fetch_instrument_spec


INST_ID = "SOL-USDT"
BUY_USDT = 10.0
LEDGER_PATH = ROOT / "data" / "orders" / "demo_orders.json"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="First demo-trading round trip: market buy 10 USDT of SOL, sell it back."
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="actually submit the demo orders; without this flag the safety gate blocks them",
    )
    args = parser.parse_args()

    credentials = load_demo_credentials()
    limits = DemoExecutionLimits(max_order_usdt=25.0)
    records = load_demo_order_ledger(LEDGER_PATH) if LEDGER_PATH.exists() else []
    executor = DemoOrderExecutor(credentials, limits, records=records)

    print("OKX Lesson 27: first demo-trading round trip")
    print(f"instrument:   {INST_ID}")
    print(f"api_key:      {credentials.masked_api_key}")
    print(f"notional cap: {limits.max_order_usdt:.2f} USDT")
    print(f"confirmed:    {args.confirm}")
    print()

    spec = fetch_instrument_spec(INST_ID)
    now_hour_ms = int(time.time() * 1000) // 3_600_000 * 3_600_000

    buy = executor.submit(
        OrderRequest(
            client_order_id=f"demo:{INST_ID}:{now_hour_ms}:BUY:lesson27",
            inst_id=INST_ID,
            side="BUY",
            quote_amount_usdt=BUY_USDT,
            base_quantity=0.0,
            reference_price=0.0,
            created_at_ms=now_hour_ms,
            reason="lesson 27 first demo order",
        ),
        confirmed=args.confirm,
    )
    print(f"BUY  -> {buy.status}: {buy.message}")
    if buy.status == "FILLED":
        print(f"        fill={buy.fill_price:.4f} qty={buy.fill_quantity:.6f} "
              f"fee={buy.fee:.8f} {buy.fee_currency}")

        available = buy.fill_quantity + (buy.fee if buy.fee_currency == INST_ID.split("-")[0] else 0.0)
        sell_quantity = quantize_to_lot(available, spec.lot_size)
        if sell_quantity >= spec.min_size:
            sell = executor.submit(
                OrderRequest(
                    client_order_id=f"demo:{INST_ID}:{now_hour_ms}:SELL:lesson27",
                    inst_id=INST_ID,
                    side="SELL",
                    quote_amount_usdt=0.0,
                    base_quantity=sell_quantity,
                    reference_price=buy.fill_price,
                    created_at_ms=now_hour_ms,
                    reason="lesson 27 close the round trip",
                ),
                confirmed=args.confirm,
            )
            print(f"SELL -> {sell.status}: {sell.message}")
            if sell.status == "FILLED":
                bought_cost = BUY_USDT
                sold_proceeds = sell.fill_quantity * sell.fill_price + (
                    sell.fee if sell.fee_currency == "USDT" else 0.0
                )
                print(f"        fill={sell.fill_price:.4f} qty={sell.fill_quantity:.6f} "
                      f"fee={sell.fee:.8f} {sell.fee_currency}")
                print(f"        round_trip_cost={bought_cost - sold_proceeds:.4f} USDT "
                      "(spread + two fees: the price of admission, now measured)")
        else:
            print(f"SELL -> skipped: filled {available:.8f} below min size {spec.min_size}")

    save_demo_order_ledger(LEDGER_PATH, executor.records)
    balance = fetch_demo_balance(credentials)

    print()
    print(f"ledger:       {LEDGER_PATH} ({len(executor.records)} records)")
    print(f"demo equity:  {balance['total_equity_usd']:.2f} USD")
    print()
    if args.confirm:
        print("Lesson: a real order pipeline is judged by its paper trail --")
        print("every attempt, blocked or filled, is one auditable ledger row.")
    else:
        print("Nothing was submitted: the Lesson 12 gate requires --confirm.")
        print("Re-run with --confirm to place the demo round trip.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
