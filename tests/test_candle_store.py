from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.candle_store import (
    load_candles_csv,
    merge_candles,
    refresh_candles,
    save_candles_csv,
)
from okx_quant_lab.okx_public import Candle


def _candle(ts: int, close: float = 100.0) -> Candle:
    return Candle(
        timestamp_ms=ts,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume_base=1.0,
        volume_quote=close,
        confirmed=True,
    )


class RefreshCandlesTest(unittest.TestCase):
    def test_existing_cache_is_merged_with_latest_not_skipped(self) -> None:
        # The lesson_08 trap: a full cache must still pick up newer candles.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.csv"
            save_candles_csv(path, [_candle(1), _candle(2), _candle(3)])

            merged = refresh_candles(
                path,
                "SOL-USDT",
                target_count=3,
                fetch_latest=lambda inst_id, bar, limit: [_candle(3, 105.0), _candle(4)],
                fetch_history=lambda **kwargs: self.fail("history fetch not needed"),
            )

            self.assertEqual([c.timestamp_ms for c in merged], [1, 2, 3, 4])
            self.assertEqual(merged[2].close, 105.0)  # newer duplicate wins
            self.assertEqual(len(load_candles_csv(path)), 4)  # persisted

    def test_short_cache_is_backfilled_to_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.csv"

            merged = refresh_candles(
                path,
                "SOL-USDT",
                target_count=4,
                fetch_latest=lambda inst_id, bar, limit: [_candle(9), _candle(10)],
                fetch_history=lambda inst_id, bar, target_count: [
                    _candle(ts) for ts in range(6, 10)
                ],
            )

            self.assertEqual([c.timestamp_ms for c in merged], [6, 7, 8, 9, 10])

    def test_retention_trims_the_saved_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.csv"
            save_candles_csv(path, [_candle(ts) for ts in range(1, 6)])

            merged = refresh_candles(
                path,
                "SOL-USDT",
                target_count=2,
                retention=3,
                fetch_latest=lambda inst_id, bar, limit: [_candle(6)],
                fetch_history=lambda **kwargs: self.fail("history fetch not needed"),
            )

            self.assertEqual([c.timestamp_ms for c in merged], [4, 5, 6])
            self.assertEqual([c.timestamp_ms for c in load_candles_csv(path)], [4, 5, 6])


class CandleStoreTest(unittest.TestCase):
    def test_round_trip_csv(self) -> None:
        candles = [
            Candle(
                timestamp_ms=2,
                open=101.0,
                high=102.0,
                low=100.0,
                close=101.5,
                volume_base=3.0,
                volume_quote=304.5,
                confirmed=True,
            ),
            Candle(
                timestamp_ms=1,
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume_base=2.0,
                volume_quote=201.0,
                confirmed=True,
            ),
        ]

        with tempfile.TemporaryDirectory(dir=ROOT) as dirname:
            path = Path(dirname) / "candles.csv"

            save_candles_csv(path, candles)
            loaded = load_candles_csv(path)

        self.assertEqual([candle.timestamp_ms for candle in loaded], [1, 2])
        self.assertEqual(loaded[0].close, 100.5)
        self.assertTrue(loaded[1].confirmed)

    def test_merge_candles_deduplicates_by_timestamp(self) -> None:
        older = Candle(
            timestamp_ms=1,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume_base=2.0,
            volume_quote=201.0,
            confirmed=True,
        )
        replacement = Candle(
            timestamp_ms=1,
            open=200.0,
            high=201.0,
            low=199.0,
            close=200.5,
            volume_base=3.0,
            volume_quote=601.5,
            confirmed=True,
        )
        newer = Candle(
            timestamp_ms=2,
            open=101.0,
            high=102.0,
            low=100.0,
            close=101.5,
            volume_base=3.0,
            volume_quote=304.5,
            confirmed=True,
        )

        candles = merge_candles([older], [newer, replacement])

        self.assertEqual([candle.timestamp_ms for candle in candles], [1, 2])
        self.assertEqual(candles[0].close, 200.5)


if __name__ == "__main__":
    unittest.main()
