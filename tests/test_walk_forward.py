from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.backtest import BacktestConfig
from okx_quant_lab.okx_public import Candle
from okx_quant_lab.walk_forward import summarize_walk_forward, walk_forward_sma


class WalkForwardTest(unittest.TestCase):
    def test_walk_forward_creates_rolling_windows(self) -> None:
        candles = _candles([100 + index for index in range(30)])

        summary = walk_forward_sma(
            candles=candles,
            train_size=12,
            test_size=6,
            step_size=6,
            fast_windows=[2, 3],
            slow_windows=[4, 5],
            base_config=BacktestConfig(fee_rate=0.001, slippage_bps=2),
        )

        self.assertEqual(len(summary.windows), 3)
        self.assertEqual([window.window_index for window in summary.windows], [1, 2, 3])
        self.assertGreaterEqual(summary.win_rate_pct, 0)

    def test_empty_summary_is_zeroed(self) -> None:
        summary = summarize_walk_forward([])

        self.assertEqual(summary.average_test_return_pct, 0.0)
        self.assertEqual(summary.median_test_return_pct, 0.0)
        self.assertEqual(summary.win_rate_pct, 0.0)


def _candles(closes: list[float]) -> list[Candle]:
    return [
        Candle(
            timestamp_ms=1_700_000_000_000 + index * 3_600_000,
            open=close,
            high=close,
            low=close,
            close=close,
            volume_base=1.0,
            volume_quote=close,
            confirmed=True,
        )
        for index, close in enumerate(closes)
    ]


if __name__ == "__main__":
    unittest.main()
