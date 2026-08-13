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

    def test_live_order_with_confirmation_and_small_cap_can_pass_gate(self) -> None:
        decision = evaluate_execution_safety(
            ExecutionIntent(
                mode="live",
                wants_to_submit_order=True,
                has_api_credentials=True,
                user_confirmed_order=True,
                max_order_usdt=25,
            )
        )

        self.assertTrue(decision.allowed)

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
