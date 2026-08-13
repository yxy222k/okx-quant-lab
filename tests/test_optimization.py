from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.backtest import BacktestConfig
from okx_quant_lab.optimization import sweep_sma_parameters, train_test_split
from okx_quant_lab.okx_public import Candle


class OptimizationTest(unittest.TestCase):
    def test_train_test_split_keeps_time_order(self) -> None:
        candles = _candles([100, 101, 102, 103, 104])

        split = train_test_split(list(reversed(candles)), train_fraction=0.6)

        self.assertEqual([c.timestamp_ms for c in split.train], [1_700_000_000_000, 1_700_003_600_000, 1_700_007_200_000])
        self.assertEqual([c.timestamp_ms for c in split.test], [1_700_010_800_000, 1_700_014_400_000])

    def test_sweep_skips_invalid_and_ranks_results(self) -> None:
        candles = _candles(
            [
                100,
                101,
                102,
                103,
                104,
                105,
                106,
                107,
                108,
                109,
                110,
                109,
                108,
                107,
                106,
                105,
                104,
                103,
                102,
                101,
                100,
                99,
                98,
                97,
            ]
        )
        split = train_test_split(candles, train_fraction=0.5)

        results = sweep_sma_parameters(
            train=split.train,
            test=split.test,
            fast_windows=[2, 3, 5],
            slow_windows=[3, 4],
            base_config=BacktestConfig(fee_rate=0.001, slippage_bps=2),
        )

        self.assertTrue(results)
        self.assertTrue(all(row.fast_window < row.slow_window for row in results))
        self.assertEqual(
            [row.train_return_pct for row in results],
            sorted([row.train_return_pct for row in results], reverse=True),
        )


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
