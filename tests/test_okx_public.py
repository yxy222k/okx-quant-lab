from __future__ import annotations

import email.message
import json
from pathlib import Path
import sys
import unittest
from unittest import mock
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import okx_quant_lab.okx_public as okx_public


class OkxPublicTest(unittest.TestCase):
    def test_fetch_historical_candles_paginates_with_after(self) -> None:
        calls: list[dict[str, str]] = []
        pages = [
            {
                "code": "0",
                "data": [
                    _row(3000, "103", confirmed="0"),
                    _row(2000, "102"),
                    _row(1000, "101"),
                ],
            },
            {
                "code": "0",
                "data": [
                    _row(0, "100"),
                ],
            },
        ]

        original = okx_public._get_json

        def fake_get_json(path: str, params: dict[str, str]) -> dict:
            calls.append(dict(params))
            return pages.pop(0)

        okx_public._get_json = fake_get_json
        try:
            candles = okx_public.fetch_historical_candles(
                "BTC-USDT",
                target_count=3,
                page_limit=3,
            )
        finally:
            okx_public._get_json = original

        self.assertEqual([c.timestamp_ms for c in candles], [0, 1000, 2000])
        self.assertEqual(calls[0], {"instId": "BTC-USDT", "bar": "1H", "limit": "3"})
        self.assertEqual(calls[1], {"instId": "BTC-USDT", "bar": "1H", "limit": "3", "after": "1000"})


class ParseCandleTest(unittest.TestCase):
    def test_parses_full_row_with_volume_quote_at_index_7(self) -> None:
        # Index 6 (volCcy) and index 7 (volCcyQuote) deliberately differ so the
        # test fails if _parse_candle ever reads the wrong column.
        row = ["1700000000000", "1.0", "2.0", "0.5", "1.5", "10", "999", "42.5", "1"]
        candle = okx_public._parse_candle(row)
        self.assertEqual(candle.timestamp_ms, 1700000000000)
        self.assertEqual(candle.open, 1.0)
        self.assertEqual(candle.high, 2.0)
        self.assertEqual(candle.low, 0.5)
        self.assertEqual(candle.close, 1.5)
        self.assertEqual(candle.volume_base, 10.0)
        self.assertEqual(candle.volume_quote, 42.5)
        self.assertTrue(candle.confirmed)

    def test_confirm_flag_zero_parses_as_unconfirmed(self) -> None:
        candle = okx_public._parse_candle(_row(1000, "5", confirmed="0"))
        self.assertFalse(candle.confirmed)

    def test_confirm_flag_one_parses_as_confirmed(self) -> None:
        candle = okx_public._parse_candle(_row(1000, "5", confirmed="1"))
        self.assertTrue(candle.confirmed)

    def test_rejects_short_row(self) -> None:
        short = ["1000", "1", "2", "0.5", "1.5", "10", "999", "42"]  # 8 fields
        with self.assertRaises(RuntimeError):
            okx_public._parse_candle(short)


class FetchCandlesTest(unittest.TestCase):
    def _payload(self) -> dict:
        return {
            "code": "0",
            "data": [
                _row(3000, "103", confirmed="0"),
                _row(1000, "101"),
                _row(2000, "102"),
            ],
        }

    def test_filters_unconfirmed_and_sorts_ascending(self) -> None:
        with mock.patch.object(
            okx_public, "_get_json", return_value=self._payload()
        ) as fake:
            candles = okx_public.fetch_candles("BTC-USDT", bar="4H", limit=50)

        self.assertEqual([c.timestamp_ms for c in candles], [1000, 2000])
        self.assertTrue(all(c.confirmed for c in candles))
        fake.assert_called_once_with(
            "/api/v5/market/candles",
            {"instId": "BTC-USDT", "bar": "4H", "limit": "50"},
        )

    def test_include_unconfirmed_keeps_all_rows(self) -> None:
        with mock.patch.object(okx_public, "_get_json", return_value=self._payload()):
            candles = okx_public.fetch_candles(
                "BTC-USDT", include_unconfirmed=True
            )

        self.assertEqual([c.timestamp_ms for c in candles], [1000, 2000, 3000])
        self.assertFalse(candles[-1].confirmed)


class FetchHistoricalDedupTest(unittest.TestCase):
    def test_overlapping_pages_dedup_and_empty_page_stops(self) -> None:
        calls: list[tuple[str, dict[str, str]]] = []
        pages = [
            {
                "code": "0",
                "data": [_row(3000, "103"), _row(2000, "102"), _row(1000, "101")],
            },
            # Overlaps the previous page at ts=1000: must dedup, not duplicate.
            {"code": "0", "data": [_row(1000, "101"), _row(0, "100")]},
            {"code": "0", "data": []},
        ]

        def fake_get_json(path: str, params: dict[str, str]) -> dict:
            calls.append((path, dict(params)))
            return pages.pop(0)

        with mock.patch.object(okx_public, "_get_json", fake_get_json):
            candles = okx_public.fetch_historical_candles(
                "ETH-USDT", target_count=10, page_limit=3
            )

        self.assertEqual([c.timestamp_ms for c in candles], [0, 1000, 2000, 3000])
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0][0], "/api/v5/market/history-candles")
        self.assertNotIn("after", calls[0][1])
        self.assertEqual(calls[1][1]["after"], "1000")
        self.assertEqual(calls[2][1]["after"], "0")


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class GetJsonRetryTest(unittest.TestCase):
    @staticmethod
    def _http_error(code: int, headers: dict[str, str] | None = None) -> HTTPError:
        msg = email.message.Message()
        for key, value in (headers or {}).items():
            msg[key] = value
        return HTTPError("https://www.okx.com/x", code, "boom", msg, None)

    def test_http_400_raises_immediately_without_retry(self) -> None:
        attempts: list[str] = []

        def fake_urlopen(request, timeout=None):
            attempts.append(request.full_url)
            raise self._http_error(400)

        sleeps: list[float] = []
        with mock.patch.object(okx_public, "urlopen", fake_urlopen), mock.patch.object(
            okx_public.time, "sleep", sleeps.append
        ):
            with self.assertRaises(RuntimeError) as ctx:
                okx_public._get_json("/api/v5/market/ticker", {"instId": "BTC-USDT"})

        self.assertEqual(len(attempts), 1)
        self.assertEqual(sleeps, [])
        self.assertIn("HTTP 400", str(ctx.exception))

    def test_429_honors_retry_after_then_succeeds(self) -> None:
        payload = {"code": "0", "data": []}
        attempts: list[int] = []

        def fake_urlopen(request, timeout=None):
            attempts.append(1)
            if len(attempts) == 1:
                raise self._http_error(429, {"Retry-After": "7"})
            return _FakeResponse(payload)

        sleeps: list[float] = []
        with mock.patch.object(okx_public, "urlopen", fake_urlopen), mock.patch.object(
            okx_public.time, "sleep", sleeps.append
        ):
            result = okx_public._get_json(
                "/api/v5/market/candles", {"instId": "BTC-USDT"}
            )

        self.assertEqual(result, payload)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(sleeps, [7.0])

    def test_three_network_failures_raise_runtime_error(self) -> None:
        attempts: list[int] = []

        def fake_urlopen(request, timeout=None):
            attempts.append(1)
            raise URLError("connection refused")

        sleeps: list[float] = []
        with mock.patch.object(okx_public, "urlopen", fake_urlopen), mock.patch.object(
            okx_public.time, "sleep", sleeps.append
        ):
            with self.assertRaises(RuntimeError) as ctx:
                okx_public._get_json("/api/v5/market/candles", {"instId": "BTC-USDT"})

        self.assertEqual(len(attempts), 3)
        self.assertEqual(len(sleeps), 2)  # sleeps only between attempts
        self.assertIn("request failed after retries", str(ctx.exception))
        self.assertIsInstance(ctx.exception.__cause__, URLError)


def _row(timestamp_ms: int, close: str, confirmed: str = "1") -> list[str]:
    return [
        str(timestamp_ms),
        close,
        close,
        close,
        close,
        "1",
        close,
        close,
        confirmed,
    ]


if __name__ == "__main__":
    unittest.main()
