from __future__ import annotations

from pathlib import Path
import sys
import unittest

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
