from __future__ import annotations

import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.candle_store import (
    candle_gaps,
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

    def test_stale_cache_gap_is_bridged_with_history(self) -> None:
        # Cache newest = ts 3, fresh fetch = ts 10..11 (bar interval 1): the
        # hole 4..9 must be backfilled even though the row count is fine.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.csv"
            save_candles_csv(path, [_candle(ts) for ts in range(1, 4)])
            history_calls: list = []

            def fake_history(inst_id, bar, target_count):
                history_calls.append(target_count)
                return [_candle(ts) for ts in range(12 - target_count, 12)]

            merged = refresh_candles(
                path,
                "SOL-USDT",
                target_count=3,
                fetch_latest=lambda inst_id, bar, limit: [_candle(10), _candle(11)],
                fetch_history=fake_history,
            )

            self.assertEqual(len(history_calls), 1)
            self.assertGreaterEqual(history_calls[0], 8)  # reaches back past ts 3
            self.assertEqual([c.timestamp_ms for c in merged], list(range(1, 12)))

    def test_contiguous_cache_never_triggers_gap_backfill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.csv"
            save_candles_csv(path, [_candle(ts) for ts in range(1, 4)])

            merged = refresh_candles(
                path,
                "SOL-USDT",
                target_count=3,
                fetch_latest=lambda inst_id, bar, limit: [_candle(4), _candle(5)],
                fetch_history=lambda **kwargs: self.fail("no gap, no backfill"),
            )

            self.assertEqual([c.timestamp_ms for c in merged], [1, 2, 3, 4, 5])

    def test_candle_gaps_reports_holes_and_bar_counts(self) -> None:
        contiguous = [_candle(ts) for ts in range(1, 6)]
        self.assertEqual(candle_gaps(contiguous), [])
        self.assertEqual(candle_gaps(contiguous[:2]), [])  # too short to infer a bar

        holed = [_candle(1), _candle(2), _candle(6), _candle(7), _candle(12)]
        self.assertEqual(candle_gaps(holed), [(2, 6, 3), (7, 12, 4)])

    def test_interior_gap_is_left_alone_but_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.csv"
            # Cache already holds a hole at 3..7, and it is contiguous with the fetch.
            save_candles_csv(path, [_candle(1), _candle(2), _candle(8), _candle(9)])

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                merged = refresh_candles(
                    path,
                    "SOL-USDT",
                    target_count=4,
                    fetch_latest=lambda inst_id, bar, limit: [_candle(9), _candle(10)],
                    fetch_history=lambda **kwargs: self.fail("repair is opt-in"),
                )

            self.assertEqual([c.timestamp_ms for c in merged], [1, 2, 8, 9, 10])
            self.assertIn("gap(s)", stderr.getvalue())
            self.assertIn("repair_gaps=True", stderr.getvalue())

    def test_repair_gaps_backfills_the_interior_hole(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.csv"
            save_candles_csv(path, [_candle(1), _candle(2), _candle(8), _candle(9)])
            asked: list = []

            def fake_history(inst_id, bar, target_count):
                asked.append(target_count)
                return [_candle(ts) for ts in range(11 - target_count, 11)]

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                merged = refresh_candles(
                    path,
                    "SOL-USDT",
                    target_count=4,
                    repair_gaps=True,
                    fetch_latest=lambda inst_id, bar, limit: [_candle(9), _candle(10)],
                    fetch_history=fake_history,
                )

            self.assertEqual([c.timestamp_ms for c in merged], list(range(1, 11)))
            self.assertEqual(asked, [10])  # reached back past the oldest hole
            self.assertEqual(stderr.getvalue(), "")  # repaired, so nothing to warn about

    def test_unfillable_gap_still_warns_after_repair_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.csv"
            save_candles_csv(path, [_candle(1), _candle(2), _candle(8), _candle(9)])

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                refresh_candles(
                    path,
                    "SOL-USDT",
                    target_count=4,
                    repair_gaps=True,
                    fetch_latest=lambda inst_id, bar, limit: [_candle(9), _candle(10)],
                    fetch_history=lambda inst_id, bar, target_count: [],  # venue has nothing
                )

            self.assertIn("gap(s)", stderr.getvalue())
            self.assertNotIn("repair_gaps=True", stderr.getvalue())  # already tried

    def test_network_failure_falls_back_to_warm_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.csv"
            save_candles_csv(path, [_candle(ts) for ts in range(1, 6)])

            def failing_fetch(inst_id, bar, limit):
                raise RuntimeError("request failed after retries")

            merged = refresh_candles(
                path,
                "SOL-USDT",
                target_count=3,
                retention=4,
                fetch_latest=failing_fetch,
                fetch_history=lambda **kwargs: self.fail("offline: no history call"),
            )

            self.assertEqual([c.timestamp_ms for c in merged], [2, 3, 4, 5])
            # cache untouched on disk
            self.assertEqual(len(load_candles_csv(path)), 5)

    def test_network_failure_with_cold_cache_still_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.csv"

            def failing_fetch(inst_id, bar, limit):
                raise RuntimeError("request failed after retries")

            with self.assertRaises(RuntimeError):
                refresh_candles(path, "SOL-USDT", fetch_latest=failing_fetch)

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

        with tempfile.TemporaryDirectory() as dirname:
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
