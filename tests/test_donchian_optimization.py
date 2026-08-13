from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.donchian_optimization import sweep_donchian_parameters
from okx_quant_lab.donchian_strategy import DonchianBacktestConfig
from okx_quant_lab.okx_public import Candle


class DonchianSweepTest(unittest.TestCase):
    def test_sweep_skips_invalid_pairs_and_sorts(self) -> None:
        trend = [100 + step for step in range(30)]
        train = _candles(trend)
        test = _candles([130 - step for step in range(30)], start_index=30)

        results = sweep_donchian_parameters(
            train=train,
            test=test,
            entry_windows=[5, 10],
            exit_windows=[3, 5, 10],
            base_config=DonchianBacktestConfig(fee_rate=0.001, slippage_bps=2.0),
        )

        # exit >= entry pairs are skipped: valid pairs are (5,3), (10,3), (10,5).
        self.assertEqual(len(results), 3)
        train_returns = [result.train_return_pct for result in results]
        self.assertEqual(train_returns, sorted(train_returns, reverse=True))
        for result in results:
            self.assertLess(result.exit_window, result.entry_window)
            self.assertAlmostEqual(
                result.overfit_gap_pct,
                result.train_return_pct - result.test_return_pct,
            )

    def test_uptrend_train_beats_downtrend_test(self) -> None:
        train = _candles([100 + step for step in range(40)])
        test = _candles([140 - 2 * step for step in range(40)], start_index=40)

        results = sweep_donchian_parameters(
            train=train,
            test=test,
            entry_windows=[8],
            exit_windows=[4],
            base_config=DonchianBacktestConfig(fee_rate=0, slippage_bps=0),
        )

        self.assertEqual(len(results), 1)
        self.assertGreater(results[0].train_return_pct, 0)
        self.assertGreater(results[0].overfit_gap_pct, 0)

    def test_rejects_empty_segments(self) -> None:
        with self.assertRaises(ValueError):
            sweep_donchian_parameters(
                train=[],
                test=_candles([100, 101]),
                entry_windows=[5],
                exit_windows=[3],
                base_config=DonchianBacktestConfig(),
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
