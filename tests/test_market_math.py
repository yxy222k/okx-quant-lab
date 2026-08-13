from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.market_math import spread_stats


class SpreadStatsTest(unittest.TestCase):
    def test_spread_stats(self) -> None:
        stats = spread_stats(bid=99.0, ask=101.0)

        self.assertEqual(stats.mid, 100.0)
        self.assertEqual(stats.spread, 2.0)
        self.assertEqual(stats.spread_bps, 200.0)

    def test_rejects_crossed_market(self) -> None:
        with self.assertRaises(ValueError):
            spread_stats(bid=101.0, ask=99.0)


if __name__ == "__main__":
    unittest.main()
