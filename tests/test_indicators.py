from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.indicators import relative_strength_index, simple_moving_average


class IndicatorsTest(unittest.TestCase):
    def test_simple_moving_average(self) -> None:
        self.assertEqual(
            simple_moving_average([1, 2, 3, 4], 3),
            [None, None, 2.0, 3.0],
        )

    def test_rsi_rising_market_reaches_100(self) -> None:
        rsi = relative_strength_index([1, 2, 3, 4, 5, 6], period=3)

        self.assertEqual(rsi[0:3], [None, None, None])
        self.assertEqual(rsi[3], 100.0)
        self.assertEqual(rsi[-1], 100.0)

    def test_rsi_flat_market_is_neutral(self) -> None:
        rsi = relative_strength_index([5, 5, 5, 5, 5], period=3)

        self.assertEqual(rsi[3], 50.0)


if __name__ == "__main__":
    unittest.main()
