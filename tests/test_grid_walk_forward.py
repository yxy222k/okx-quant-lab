from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.grid_walk_forward import walk_forward_grid
from okx_quant_lab.okx_public import Candle


class GridWalkForwardTest(unittest.TestCase):
    def test_rolls_expected_number_of_windows(self) -> None:
        closes = [100, 92] * 15  # 30 oscillating candles
        summary = walk_forward_grid(
            _candles(closes),
            train_size=10,
            test_size=5,
            step_size=5,
            range_pcts=[15.0],
            grid_counts=[4],
            fee_rate=0,
        )

        self.assertEqual(len(summary.windows), 4)
        self.assertEqual(
            [window.window_index for window in summary.windows],
            [1, 2, 3, 4],
        )

    def test_summary_matches_window_returns(self) -> None:
        closes = [100, 92] * 15
        summary = walk_forward_grid(
            _candles(closes),
            train_size=10,
            test_size=5,
            step_size=5,
            range_pcts=[10.0, 15.0],
            grid_counts=[4, 8],
            fee_rate=0.001,
        )

        test_returns = [window.selected.test_return_pct for window in summary.windows]
        self.assertAlmostEqual(
            summary.average_test_return_pct,
            sum(test_returns) / len(test_returns),
        )
        expected_multiplier = 1.0
        for value in test_returns:
            expected_multiplier *= 1 + value / 100
        self.assertAlmostEqual(
            summary.cumulative_test_return_pct,
            (expected_multiplier - 1) * 100,
        )
        self.assertTrue(0 <= summary.win_rate_pct <= 100)

    def test_rejects_short_history(self) -> None:
        with self.assertRaises(ValueError):
            walk_forward_grid(
                _candles([100, 92, 100]),
                train_size=10,
                test_size=5,
                step_size=5,
                range_pcts=[15.0],
                grid_counts=[4],
            )


def _candles(closes: list[float]) -> list[Candle]:
    candles = []
    previous = closes[0]
    for index, close in enumerate(closes):
        candles.append(
            Candle(
                timestamp_ms=1_700_000_000_000 + index * 3_600_000,
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
