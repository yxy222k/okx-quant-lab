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


def setUpModule() -> None:
    # Orders a fake reports as still working are re-polled with backoff; no
    # test here should spend real seconds in that loop.
    import okx_quant_lab.demo_execution as mod
    global _ORIGINAL_SLEEP
    _ORIGINAL_SLEEP = mod._SLEEP
    mod._SLEEP = lambda seconds: None


def tearDownModule() -> None:
    import okx_quant_lab.demo_execution as mod
    mod._SLEEP = _ORIGINAL_SLEEP


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

    def _no_sleep(self) -> None:
        from okx_quant_lab import demo_execution as mod

        original = mod._SLEEP
        mod._SLEEP = lambda seconds: None
        self.addCleanup(lambda: setattr(mod, "_SLEEP", original))

    def test_timed_out_post_with_no_exchange_order_lands_error_never_resubmits(self) -> None:
        # OKX only dedups clOrdIds among PENDING orders, so "not found now" is
        # not proof the first POST never executed — the policy is: no resubmit.
        self._no_sleep()
        posts: list = []
        probes: list = []

        def request_fn(credentials, method, path, body=None):
            if method == "POST":
                posts.append(dict(body))
                raise TimeoutError()
            probes.append(path)
            raise OkxApiError("OKX API error: code=51603", code="51603")

        executor = DemoOrderExecutor(CREDENTIALS, DemoExecutionLimits(), request_fn=request_fn)
        record = executor.submit(_request(), confirmed=True)

        self.assertEqual(record.status, "ERROR")
        self.assertIn("outcome unknown", record.message)
        self.assertEqual(len(posts), 1)  # never resubmitted
        self.assertEqual(len(probes), 2)  # probe + grace re-probe

        retried = executor.submit(_request(), confirmed=True)
        self.assertEqual(retried.status, "DUPLICATE")

    def test_duplicate_clordid_rejection_reconciles_to_the_existing_order(self) -> None:
        # Real transport shape: OKX rejects with HTTP 200 {code:"1"} and the
        # sCode in data[0], which private_request raises as OkxApiError.
        def request_fn(credentials, method, path, body=None):
            if method == "POST":
                raise OkxApiError(
                    'OKX API error: code=1 sCode=51016',
                    code="1", scode="51016", smsg="clOrdId duplicated",
                )
            if "clOrdId=" in path:
                return {"code": "0", "data": [{"ordId": "ord-7", "state": "live"}]}
            return {"code": "0", "data": [{"state": "live", "avgPx": "", "accFillSz": "",
                                           "fee": "", "feeCcy": ""}]}

        executor = DemoOrderExecutor(CREDENTIALS, DemoExecutionLimits(), request_fn=request_fn)
        record = executor.submit(_request(), confirmed=True)

        self.assertEqual(record.status, "SUBMITTED")
        self.assertEqual(record.exchange_order_id, "ord-7")

    def test_real_shape_exchange_rejection_is_recorded_as_rejected(self) -> None:
        # A definitive per-order sCode (not a duplicate) must book REJECTED,
        # not ERROR — the sCode travels inside OkxApiError on the real wire.
        def request_fn(credentials, method, path, body=None):
            if method == "POST":
                raise OkxApiError(
                    "OKX API error: code=1 sCode=51121",
                    code="1", scode="51121", smsg="Order quantity precision error",
                )
            raise AssertionError("no probe expected for a definitive rejection")

        executor = DemoOrderExecutor(CREDENTIALS, DemoExecutionLimits(), request_fn=request_fn)
        record = executor.submit(_request(), confirmed=True)

        self.assertEqual(record.status, "REJECTED")
        self.assertIn("precision", record.message)

    def test_rate_limited_post_retries_once_with_the_same_clordid(self) -> None:
        # 429 means the rate limiter rejected the request before the order
        # engine saw it — the one provably-safe POST retry.
        self._no_sleep()
        posts: list = []

        def request_fn(credentials, method, path, body=None):
            if method == "POST":
                posts.append(dict(body))
                if len(posts) == 1:
                    raise OkxApiError("OKX API HTTP 429", code="50011", http_status=429)
                return {"code": "0", "data": [{"sCode": "0", "ordId": "ord-3"}]}
            return {
                "code": "0",
                "data": [{"state": "filled", "avgPx": "100", "accFillSz": "0.1",
                          "fee": "-0.01", "feeCcy": "USDT"}],
            }

        executor = DemoOrderExecutor(CREDENTIALS, DemoExecutionLimits(), request_fn=request_fn)
        record = executor.submit(_request(), confirmed=True)

        self.assertEqual(record.status, "FILLED")
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[0]["clOrdId"], posts[1]["clOrdId"])

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

    def test_terminal_order_states_are_not_reported_as_submitted(self) -> None:
        # OKX demo cancels market orders that slip past its price-protection
        # band (thin simulated book); those are terminal, not "still working".
        cases = [
            ("filled", "0.1", "FILLED"),
            ("canceled", "0", "CANCELED"),
            ("mmp_canceled", "0", "CANCELED"),
            ("canceled", "0.04", "PARTIAL"),
            ("live", "0", "SUBMITTED"),
            ("partially_filled", "0.04", "SUBMITTED"),
        ]
        for index, (state, filled, expected) in enumerate(cases):
            with self.subTest(state=state, filled=filled):
                def request_fn(credentials, method, path, body=None, _s=state, _f=filled):
                    if method == "POST":
                        return {"code": "0", "data": [{"sCode": "0", "ordId": "ord-x"}]}
                    return {
                        "code": "0",
                        "data": [{"ordId": "ord-x", "state": _s, "avgPx": "100",
                                  "accFillSz": _f, "fee": "-0.01", "feeCcy": "USDT"}],
                    }

                executor = DemoOrderExecutor(
                    CREDENTIALS, DemoExecutionLimits(), request_fn=request_fn
                )
                request = _request(client_order_id=f"state:{index}")
                record = executor.submit(request, confirmed=True)

                self.assertEqual(record.status, expected)
                self.assertIn(state, record.message)
                # Every one of these reached the exchange, so the id is spent.
                self.assertEqual(
                    executor.submit(request, confirmed=True).status, "DUPLICATE"
                )

    def test_partial_cancel_message_flags_manual_reconciliation(self) -> None:
        def request_fn(credentials, method, path, body=None):
            if method == "POST":
                return {"code": "0", "data": [{"sCode": "0", "ordId": "ord-p"}]}
            return {
                "code": "0",
                "data": [{"ordId": "ord-p", "state": "canceled", "avgPx": "100",
                          "accFillSz": "0.04", "fee": "-0.01", "feeCcy": "USDT"}],
            }

        executor = DemoOrderExecutor(CREDENTIALS, DemoExecutionLimits(), request_fn=request_fn)
        record = executor.submit(_request(), confirmed=True)

        self.assertEqual(record.status, "PARTIAL")
        self.assertAlmostEqual(record.fill_quantity, 0.04)
        self.assertIn("drifted", record.message)

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


def _scripted_details(states: list) -> callable:
    """POST succeeds; each order GET returns the next scripted state (the last
    one repeats). An Exception instance in the script is raised instead."""
    script = list(states)
    calls = {"get": 0}

    def request_fn(credentials, method, path, body=None):
        if method == "POST":
            return {"code": "0", "data": [{"sCode": "0", "ordId": "ord-late"}]}
        calls["get"] += 1
        step = script.pop(0) if len(script) > 1 else script[0]
        if isinstance(step, Exception):
            raise step
        filled = "0.0985" if step == "filled" else "0"
        return {"code": "0", "data": [{"ordId": "ord-late", "state": step, "avgPx": "101.5",
                                       "accFillSz": filled, "fee": "-0.0000985",
                                       "feeCcy": "SOL"}]}

    request_fn.calls = calls
    return request_fn


class LateFillTest(unittest.TestCase):
    """A market order can still be working when first queried (2026-09-23: an
    ETH buy filled 10.1 s after create and was never booked)."""

    def setUp(self) -> None:
        import okx_quant_lab.demo_execution as mod
        self.sleeps: list = []
        original = mod._SLEEP
        mod._SLEEP = self.sleeps.append
        self.addCleanup(lambda: setattr(mod, "_SLEEP", original))
        self.mod = mod

    def test_order_still_working_is_polled_until_filled(self) -> None:
        request_fn = _scripted_details(["live", "live", "filled"])
        executor = DemoOrderExecutor(CREDENTIALS, DemoExecutionLimits(), request_fn=request_fn)

        record = executor.submit(_request(), confirmed=True)

        self.assertEqual(record.status, "FILLED")
        self.assertAlmostEqual(record.fill_quantity, 0.0985)
        self.assertEqual(request_fn.calls["get"], 3)
        self.assertEqual(len(self.sleeps), 2)

    def test_polling_is_bounded_then_records_submitted(self) -> None:
        request_fn = _scripted_details(["live"])
        executor = DemoOrderExecutor(CREDENTIALS, DemoExecutionLimits(), request_fn=request_fn)

        record = executor.submit(_request(), confirmed=True)

        self.assertEqual(record.status, "SUBMITTED")
        self.assertEqual(self.sleeps, list(self.mod._FILL_POLL_DELAYS))
        self.assertEqual(request_fn.calls["get"], len(self.mod._FILL_POLL_DELAYS) + 1)

    def test_failed_requery_keeps_submitted_not_error(self) -> None:
        request_fn = _scripted_details(["live", TimeoutError("read timed out")])
        executor = DemoOrderExecutor(CREDENTIALS, DemoExecutionLimits(), request_fn=request_fn)

        record = executor.submit(_request(), confirmed=True)

        self.assertEqual(record.status, "SUBMITTED")
        self.assertEqual(record.exchange_order_id, "ord-late")

    def test_refresh_submitted_resolves_a_late_fill_in_place(self) -> None:
        request_fn = _scripted_details(["live"])
        executor = DemoOrderExecutor(CREDENTIALS, DemoExecutionLimits(), request_fn=request_fn)
        executor.submit(_request("a"), confirmed=True)
        submitted = executor.records[0]
        saved: list = []
        later = DemoOrderExecutor(
            CREDENTIALS, DemoExecutionLimits(), records=[submitted],
            request_fn=_scripted_details(["filled"]), on_record=saved.append,
        )

        resolved = later.refresh_submitted()

        self.assertEqual(len(resolved), 1)
        old, new = resolved[0]
        self.assertEqual((old.status, new.status), ("SUBMITTED", "FILLED"))
        self.assertAlmostEqual(new.fill_quantity, 0.0985)
        self.assertIn("resolved to state=filled", new.message)
        self.assertEqual(later.records, [new])
        self.assertEqual(saved, [])  # the caller persists, state first
        # The id stays consumed.
        self.assertEqual(later.submit(_request("a"), confirmed=True).status, "DUPLICATE")

    def test_refresh_submitted_leaves_working_and_unreachable_orders_alone(self) -> None:
        executor = DemoOrderExecutor(CREDENTIALS, DemoExecutionLimits(),
                                     request_fn=_scripted_details(["live"]))
        executor.submit(_request("b"), confirmed=True)
        submitted = executor.records[0]
        for script in (["live"], [OSError("down")]):
            with self.subTest(script=script):
                later = DemoOrderExecutor(CREDENTIALS, DemoExecutionLimits(),
                                          records=[submitted],
                                          request_fn=_scripted_details(script))
                self.assertEqual(later.refresh_submitted(), [])
                self.assertEqual(later.records, [submitted])
