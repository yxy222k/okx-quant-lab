from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.safety import ExecutionIntent, evaluate_execution_safety


class SafetyTest(unittest.TestCase):
    def test_paper_mode_without_order_is_allowed_without_credentials(self) -> None:
        decision = evaluate_execution_safety(
            ExecutionIntent(
                mode="paper",
                wants_to_submit_order=False,
                has_api_credentials=False,
                user_confirmed_order=False,
                max_order_usdt=0,
            )
        )

        self.assertTrue(decision.allowed)

    def test_demo_order_requires_credentials_and_confirmation(self) -> None:
        decision = evaluate_execution_safety(
            ExecutionIntent(
                mode="demo",
                wants_to_submit_order=True,
                has_api_credentials=False,
                user_confirmed_order=False,
                max_order_usdt=25,
            )
        )

        self.assertFalse(decision.allowed)

    def test_live_mode_is_refused_without_the_env_switch(self) -> None:
        # Defense in depth: even a fully-confirmed live intent is blocked
        # unless the operator explicitly sets OKX_ALLOW_LIVE=1.
        import os

        intent = ExecutionIntent(
            mode="live",
            wants_to_submit_order=True,
            has_api_credentials=True,
            user_confirmed_order=True,
            max_order_usdt=25,
        )

        os.environ.pop("OKX_ALLOW_LIVE", None)
        decision = evaluate_execution_safety(intent)
        self.assertFalse(decision.allowed)
        mode_check = next(c for c in decision.checks if c.name == "mode")
        self.assertIn("OKX_ALLOW_LIVE", mode_check.message)

        os.environ["OKX_ALLOW_LIVE"] = "1"
        try:
            self.assertTrue(evaluate_execution_safety(intent).allowed)
        finally:
            os.environ.pop("OKX_ALLOW_LIVE", None)

    def test_live_order_cap_blocks_large_notional(self) -> None:
        decision = evaluate_execution_safety(
            ExecutionIntent(
                mode="live",
                wants_to_submit_order=True,
                has_api_credentials=True,
                user_confirmed_order=True,
                max_order_usdt=1_000,
            )
        )

        self.assertFalse(decision.allowed)


if __name__ == "__main__":
    unittest.main()
