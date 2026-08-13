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
from okx_quant_lab.okx_demo_private import DemoCredentials, OkxApiError


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

    def test_network_failures_are_recorded_and_consume_the_id(self) -> None:
        # TimeoutError/URLError are OSError subclasses that private_request does
        # NOT wrap into RuntimeError; they must still land in the ledger.
        from urllib.error import HTTPError

        failures = [
            TimeoutError(),  # bare: str() is empty, message needs the type name
            HTTPError("https://okx.com", 502, "bad gateway", None, None),
            ValueError("Expecting value: line 1 column 1 (char 0)"),  # non-JSON body
        ]
        for index, failure in enumerate(failures):
            with self.subTest(failure=type(failure).__name__):
                def failing(credentials, method, path, body=None, _error=failure):
                    raise _error

                executor = DemoOrderExecutor(
                    CREDENTIALS, DemoExecutionLimits(), request_fn=failing
                )
                request = _request(client_order_id=f"net:{index}")

                record = executor.submit(request, confirmed=True)
                self.assertEqual(record.status, "ERROR")
                self.assertIn(type(failure).__name__, record.message)

                retried = executor.submit(request, confirmed=True)
                self.assertEqual(retried.status, "DUPLICATE")
                self.assertEqual(len(executor.records), 1)

    def test_error_record_survives_ledger_roundtrip_and_still_blocks_retry(self) -> None:
        def failing(credentials, method, path, body=None):
            raise TimeoutError()

        executor = DemoOrderExecutor(CREDENTIALS, DemoExecutionLimits(), request_fn=failing)
        executor.submit(_request(), confirmed=True)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            save_demo_order_ledger(path, executor.records)
            reloaded = DemoOrderExecutor(
                CREDENTIALS,
                DemoExecutionLimits(),
                records=load_demo_order_ledger(path),
                request_fn=failing,
            )

        retried = reloaded.submit(_request(), confirmed=True)
        self.assertEqual(retried.status, "DUPLICATE")

    def test_timed_out_post_reconciles_via_clordid_instead_of_resubmitting(self) -> None:
        # POST times out but actually landed; the probe finds it, no second POST.
        posts: list = []

        def request_fn(credentials, method, path, body=None):
            if method == "POST":
                posts.append(body)
                raise TimeoutError()
            if "clOrdId=" in path:
                return {"code": "0", "data": [{"ordId": "ord-9", "state": "filled"}]}
            return {
                "code": "0",
                "data": [{"state": "filled", "avgPx": "100", "accFillSz": "0.1",
                          "fee": "-0.01", "feeCcy": "USDT"}],
            }

        executor = DemoOrderExecutor(CREDENTIALS, DemoExecutionLimits(), request_fn=request_fn)
        record = executor.submit(_request(), confirmed=True)

        self.assertEqual(record.status, "FILLED")
        self.assertEqual(record.exchange_order_id, "ord-9")
        self.assertEqual(len(posts), 1)  # never resubmitted

    def test_timed_out_post_resubmits_same_clordid_when_exchange_has_no_order(self) -> None:
        posts: list = []

        def request_fn(credentials, method, path, body=None):
            if method == "POST":
                posts.append(dict(body))
                if len(posts) == 1:
                    raise TimeoutError()
                return {"code": "0", "data": [{"sCode": "0", "ordId": "ord-2"}]}
            if "clOrdId=" in path:
                raise OkxApiError("OKX API error: code=51603", code="51603")
            return {
                "code": "0",
                "data": [{"state": "filled", "avgPx": "100", "accFillSz": "0.1",
                          "fee": "-0.01", "feeCcy": "USDT"}],
            }

        executor = DemoOrderExecutor(CREDENTIALS, DemoExecutionLimits(), request_fn=request_fn)
        record = executor.submit(_request(), confirmed=True)

        self.assertEqual(record.status, "FILLED")
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[0]["clOrdId"], posts[1]["clOrdId"])  # idempotent retry

    def test_duplicate_clordid_rejection_reconciles_to_the_existing_order(self) -> None:
        def request_fn(credentials, method, path, body=None):
            if method == "POST":
                return {"code": "0", "data": [{"sCode": "51016", "sMsg": "clOrdId duplicated"}]}
            if "clOrdId=" in path:
                return {"code": "0", "data": [{"ordId": "ord-7", "state": "live"}]}
            return {"code": "0", "data": [{"state": "live", "avgPx": "", "accFillSz": "",
                                           "fee": "", "feeCcy": ""}]}

        executor = DemoOrderExecutor(CREDENTIALS, DemoExecutionLimits(), request_fn=request_fn)
        record = executor.submit(_request(), confirmed=True)

        self.assertEqual(record.status, "SUBMITTED")
        self.assertEqual(record.exchange_order_id, "ord-7")

    def test_unreachable_probe_after_timeout_lands_as_error_and_consumes_id(self) -> None:
        def request_fn(credentials, method, path, body=None):
            raise TimeoutError()  # POST and probe both dead

        executor = DemoOrderExecutor(CREDENTIALS, DemoExecutionLimits(), request_fn=request_fn)
        record = executor.submit(_request(), confirmed=True)
        self.assertEqual(record.status, "ERROR")

        retried = executor.submit(_request(), confirmed=True)
        self.assertEqual(retried.status, "DUPLICATE")

    def test_non_retryable_api_error_does_not_resubmit(self) -> None:
        posts: list = []

        def request_fn(credentials, method, path, body=None):
            posts.append(method)
            raise OkxApiError("OKX API HTTP 401: no permission", code="50120", http_status=401)

        executor = DemoOrderExecutor(CREDENTIALS, DemoExecutionLimits(), request_fn=request_fn)
        record = executor.submit(_request(), confirmed=True)

        self.assertEqual(record.status, "ERROR")
        self.assertEqual(posts, ["POST"])  # no retry, no probe

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
