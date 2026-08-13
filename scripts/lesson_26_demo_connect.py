#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.okx_demo_private import (
    DEFAULT_ENV_PATH,
    fetch_demo_balance,
    load_demo_credentials,
)


def main() -> int:
    print("OKX Lesson 26: demo-trading connectivity self-check (read-only)")
    print(f"credentials:  {DEFAULT_ENV_PATH}")

    credentials = load_demo_credentials()
    print(f"api_key:      {credentials.masked_api_key}")
    print("environment:  demo (x-simulated-trading: 1, hard-coded)")

    balance = fetch_demo_balance(credentials)
    print(f"total_equity: {balance['total_equity_usd']:.2f} USD")
    if balance["currencies"]:
        for currency, equity in sorted(balance["currencies"].items()):
            print(f"  {currency:<8} {equity:.8f}")
    else:
        print("  (no non-zero balances)")

    print()
    print("This check is read-only. No order endpoint exists in this module yet;")
    print("order submission arrives only behind the Lesson 12 safety gates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
