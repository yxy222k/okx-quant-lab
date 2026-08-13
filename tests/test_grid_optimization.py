from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.grid_optimization import sweep_grid_parameters
from okx_quant_lab.okx_public import Candle


class GridSweepTest(unittest.TestCase):
    def test_sweep_reports_train_test_gap(self) -> None:
        # Train oscillates inside the range; test trends down and out of it.
        train = _candles([100, 92, 100, 92, 100, 92, 100, 92, 100, 92])
        test = _candles([100, 95, 90, 85, 80, 75, 70, 65, 60, 55], start_index=10)

        results = sweep_grid_parameters(
            train=train,
            test=test,
            range_pcts=[10.0, 20.0],
            grid_counts=[4, 8],
            fee_rate=0.001,
        )

        self.assertEqual(len(results), 4)
        train_returns = [result.train_return_pct for result in results]
        self.assertEqual(train_returns, sorted(train_returns, reverse=True))
        for result in results:
            self.assertAlmostEqual(
                result.overfit_gap_pct,
                result.train_return_pct - result.test_return_pct,
            )

        best = results[0]
        self.assertGreater(best.train_trips, 0)
        self.assertLess(best.test_return_pct, 0)
        self.assertGreater(best.test_open_slots, 0)

    def test_anchors_each_segment_at_its_own_start(self) -> None:
        # The test segment trades at 10x the train prices. If the grid were
        # anchored on train prices it could never fill a single test order.
        train = _candles([100, 92, 100, 92, 100, 92])
        test = _candles([1000, 920, 1000, 920, 1000, 920], start_index=6)

        results = sweep_grid_parameters(
            train=train,
            test=test,
            range_pcts=[15.0],
            grid_counts=[4],
            fee_rate=0,
        )

        self.assertEqual(len(results), 1)
        self.assertGreater(results[0].test_trips, 0)

    def test_rejects_empty_segments(self) -> None:
        with self.assertRaises(ValueError):
            sweep_grid_parameters(
                train=[],
                test=_candles([100, 92]),
                range_pcts=[10.0],
                grid_counts=[4],
            )


def _candles(closes: list[float], start_index: int = 0) -> list[Candle]:
    candles = []
    previous = closes[0]
    for offset, close in enumerate(closes):
        candles.append(
            Candle(
                timestamp_ms=1_700_000_000_000 + (start_index + offset) * 3_600_000,
                open=previous,
                high=max(previous, close),
                low=min(previous, close),
                close=close,
                volume_base=1.0,
                volume_quote=close,
                confirmed=True,
            )
        )
        previous = close
    return candles


if __name__ == "__main__":
    unittest.main()
