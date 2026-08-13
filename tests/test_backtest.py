from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.backtest import BacktestConfig, run_sma_backtest
from okx_quant_lab.okx_public import Candle


class SmaBacktestTest(unittest.TestCase):
    def test_charges_buy_and_sell_fees(self) -> None:
        candles = _candles([100, 101, 102, 103, 104, 103, 102, 101])
        config = BacktestConfig(
            initial_cash=1_000,
            fast_window=2,
            slow_window=3,
            fee_rate=0.001,
        )

        result = run_sma_backtest(candles, config)

        self.assertEqual([trade.side for trade in result.trades], ["BUY", "SELL"])
        self.assertAlmostEqual(result.trades[0].fee, 1.0)
        self.assertGreater(result.trades[1].fee, 0)
        self.assertLess(result.final_equity, 1_000)

    def test_slippage_worsens_fill_prices(self) -> None:
        candles = _candles([100, 101, 102, 103, 104, 103, 102, 101])
        config = BacktestConfig(
            initial_cash=1_000,
            fast_window=2,
            slow_window=3,
            fee_rate=0,
            slippage_bps=100,
        )

        result = run_sma_backtest(candles, config)

        self.assertEqual([trade.side for trade in result.trades], ["BUY", "SELL"])
        self.assertAlmostEqual(result.trades[0].price, 104.03)
        self.assertAlmostEqual(result.trades[1].price, 99.99)

    def test_rejects_not_enough_candles(self) -> None:
        with self.assertRaises(ValueError):
            run_sma_backtest(
                _candles([100, 101, 102]),
                BacktestConfig(fast_window=2, slow_window=3),
            )

    def test_result_is_invariant_to_input_order(self) -> None:
        ordered = _candles([100, 101, 102, 103, 104, 103, 102, 101])
        shuffled = [ordered[i] for i in (3, 0, 5, 1, 7, 2, 6, 4)]
        config = BacktestConfig(fast_window=2, slow_window=3, fee_rate=0.001)

        expected = run_sma_backtest(ordered, config)
        actual = run_sma_backtest(shuffled, config)

        self.assertEqual(actual.final_equity, expected.final_equity)
        self.assertEqual(
            [t.timestamp_ms for t in actual.trades],
            [t.timestamp_ms for t in expected.trades],
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
