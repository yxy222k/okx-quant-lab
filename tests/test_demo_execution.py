from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

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
from okx_quant_lab.okx_demo_private import DemoCredentials


CREDENTIALS = DemoCredentials(api_key="k", secret_key="s", passphrase="p")


def _request(client_order_id: str = "test:1", side: str = "BUY") -> OrderRequest:
    return OrderRequest(
        client_order_id=client_order_id,
        inst_id="SOL-USDT",
        side=side,
        quote_amount_usdt=10.0 if side == "BUY" else 0.0,
        base_quantity=0.05 if side == "SELL" else 0.0,
        reference_price=100.0,
        created_at_ms=1_700_000_000_000,
        reason="test",
    )


def _happy_request_fn(calls: list) -> callable:
    def fake_request(credentials, method, path, body=None):
        calls.append((method, path, body))
        if method == "POST":
            return {"code": "0", "data": [{"sCode": "0", "ordId": "ord-1"}]}
        return {
            "code": "0",
            "data": [
                {
                    "state": "filled",
                    "avgPx": "101.5",
                    "accFillSz": "0.0985",
                    "fee": "-0.0000985",
                    "feeCcy": "SOL",
                }
            ],
        }

    return fake_request


class DemoExecutorTest(unittest.TestCase):
    def test_confirmed_order_fills_and_lands_in_ledger(self) -> None:
        calls: list = []
        executor = DemoOrderExecutor(
            CREDENTIALS, DemoExecutionLimits(), request_fn=_happy_request_fn(calls)
        )

        record = executor.submit(_request(), confirmed=True)

        self.assertEqual(record.status, "FILLED")
        self.assertEqual(record.exchange_order_id, "ord-1")
        self.assertAlmostEqual(record.fill_price, 101.5)
        self.assertAlmostEqual(record.fill_quantity, 0.0985)
        self.assertEqual(len(executor.records), 1)

        post_method, post_path, post_body = calls[0]
        self.assertEqual((post_method, post_path), ("POST", "/api/v5/trade/order"))
        self.assertEqual(post_body["tgtCcy"], "quote_ccy")
        self.assertEqual(len(post_body["clOrdId"]), 32)
        self.assertTrue(post_body["clOrdId"].isalnum())

    def test_unconfirmed_order_is_blocked_and_never_hits_exchange(self) -> None:
        calls: list = []
        executor = DemoOrderExecutor(
            CREDENTIALS, DemoExecutionLimits(), request_fn=_happy_request_fn(calls)
        )

        record = executor.submit(_request(), confirmed=False)

        self.assertEqual(record.status, "BLOCKED")
        self.assertIn("order confirmation", record.message)
        self.assertEqual(calls, [])
        self.assertEqual(len(executor.records), 1)

    def test_notional_over_cap_is_blocked(self) -> None:
        calls: list = []
        executor = DemoOrderExecutor(
            CREDENTIALS, DemoExecutionLimits(max_order_usdt=5.0), request_fn=_happy_request_fn(calls)
        )

        record = executor.submit(_request(), confirmed=True)

        self.assertEqual(record.status, "BLOCKED")
        self.assertIn("exceeds cap", record.message)
        self.assertEqual(calls, [])

    def test_cap_above_100_fails_the_safety_gate(self) -> None:
        calls: list = []
        executor = DemoOrderExecutor(
            CREDENTIALS,
            DemoExecutionLimits(max_order_usdt=500.0),
            request_fn=_happy_request_fn(calls),
        )

        record = executor.submit(_request(), confirmed=True)

        self.assertEqual(record.status, "BLOCKED")
        self.assertIn("notional cap", record.message)
        self.assertEqual(calls, [])

    def test_blocked_attempt_does_not_consume_the_order_id(self) -> None:
        calls: list = []
        executor = DemoOrderExecutor(
            CREDENTIALS, DemoExecutionLimits(), request_fn=_happy_request_fn(calls)
        )

        blocked = executor.submit(_request(), confirmed=False)
        retried = executor.submit(_request(), confirmed=True)

        self.assertEqual(blocked.status, "BLOCKED")
        self.assertEqual(retried.status, "FILLED")
        self.assertEqual(len(executor.records), 2)

    def test_duplicate_client_order_id_is_not_resubmitted(self) -> None:
        calls: list = []
        executor = DemoOrderExecutor(
            CREDENTIALS, DemoExecutionLimits(), request_fn=_happy_request_fn(calls)
        )

        first = executor.submit(_request(), confirmed=True)
        second = executor.submit(_request(), confirmed=True)

        self.assertEqual(first.status, "FILLED")
        self.assertEqual(second.status, "DUPLICATE")
        self.assertEqual(len(executor.records), 1)
        self.assertEqual(len([c for c in calls if c[0] == "POST"]), 1)

    def test_api_failure_is_recorded_as_error(self) -> None:
        def failing(credentials, method, path, body=None):
            raise RuntimeError("OKX API HTTP 401: code=50120 msg=no permission")

        executor = DemoOrderExecutor(CREDENTIALS, DemoExecutionLimits(), request_fn=failing)

        record = executor.submit(_request(), confirmed=True)

        self.assertEqual(record.status, "ERROR")
        self.assertIn("50120", record.message)
        self.assertEqual(len(executor.records), 1)

        retried = executor.submit(_request(), confirmed=True)
        self.assertEqual(retried.status, "DUPLICATE")

    def test_exchange_rejection_is_recorded(self) -> None:
        def rejecting(credentials, method, path, body=None):
            return {"code": "0", "data": [{"sCode": "51000", "sMsg": "bad size"}]}

        executor = DemoOrderExecutor(
            CREDENTIALS, DemoExecutionLimits(), request_fn=rejecting
        )

        record = executor.submit(_request(), confirmed=True)

        self.assertEqual(record.status, "REJECTED")
        self.assertIn("bad size", record.message)

    def test_ledger_roundtrip(self) -> None:
        calls: list = []
        executor = DemoOrderExecutor(
            CREDENTIALS, DemoExecutionLimits(), request_fn=_happy_request_fn(calls)
        )
        executor.submit(_request(), confirmed=True)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            save_demo_order_ledger(path, executor.records)
            loaded = load_demo_order_ledger(path)

        self.assertEqual(loaded, executor.records)

    def test_quantize_to_lot(self) -> None:
        self.assertAlmostEqual(quantize_to_lot(0.098765, 0.001), 0.098)
        self.assertAlmostEqual(quantize_to_lot(0.1, 0.001), 0.1)
        with self.assertRaises(ValueError):
            quantize_to_lot(1.0, 0)


if __name__ == "__main__":
    unittest.main()
