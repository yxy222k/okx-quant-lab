#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.safety import ExecutionIntent, evaluate_execution_safety


def main() -> int:
    examples = [
        ExecutionIntent(
            mode="paper",
            wants_to_submit_order=False,
            has_api_credentials=False,
            user_confirmed_order=False,
            max_order_usdt=0,
        ),
        ExecutionIntent(
            mode="demo",
            wants_to_submit_order=True,
            has_api_credentials=False,
            user_confirmed_order=False,
            max_order_usdt=25,
        ),
        ExecutionIntent(
            mode="live",
            wants_to_submit_order=True,
            has_api_credentials=True,
            user_confirmed_order=False,
            max_order_usdt=25,
        ),
    ]

    print("OKX Lesson 12: execution safety gates")
    for intent in examples:
        decision = evaluate_execution_safety(intent)
        status = "ALLOW" if decision.allowed else "BLOCK"
        print()
        print(
            f"{status} mode={intent.mode} "
            f"submit_order={intent.wants_to_submit_order} "
            f"max_order_usdt={intent.max_order_usdt:.2f}"
        )
        for check in decision.checks:
            check_status = "PASS" if check.passed else "FAIL"
            print(f"  {check_status:<4} {check.name}: {check.message}")

    print()
    print("Lesson: safety should be executable code, not just good intentions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
