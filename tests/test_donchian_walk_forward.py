from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.donchian_strategy import DonchianBacktestConfig
from okx_quant_lab.donchian_walk_forward import walk_forward_donchian
from okx_quant_lab.okx_public import Candle


class DonchianWalkForwardTest(unittest.TestCase):
    def test_rolls_windows_and_summarizes(self) -> None:
        closes = []
        for cycle in range(10):
            closes.extend([100 + step for step in range(10)])
        candles = _candles(closes)

        summary = walk_forward_donchian(
            candles,
            train_size=30,
            test_size=15,
            step_size=15,
            entry_windows=[5, 8],
            exit_windows=[3],
            base_config=DonchianBacktestConfig(fee_rate=0.001, slippage_bps=2.0),
        )

        self.assertGreater(len(summary.windows), 0)
        test_returns = [window.selected.test_return_pct for window in summary.windows]
        self.assertAlmostEqual(
            summary.average_test_return_pct,
            sum(test_returns) / len(test_returns),
        )
        self.assertTrue(0 <= summary.win_rate_pct <= 100)

    def test_rejects_short_history(self) -> None:
        with self.assertRaises(ValueError):
            walk_forward_donchian(
                _candles([100.0] * 10),
                train_size=30,
                test_size=15,
                step_size=15,
                entry_windows=[5],
                exit_windows=[3],
                base_config=DonchianBacktestConfig(),
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
