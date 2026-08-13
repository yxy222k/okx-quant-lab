from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.okx_public import Candle
from okx_quant_lab.rsi_strategy import RsiBacktestConfig, run_rsi_mean_reversion_backtest


class RsiStrategyTest(unittest.TestCase):
    def test_rsi_strategy_can_buy_and_sell(self) -> None:
        closes = [100, 98, 96, 94, 92, 90, 92, 94, 96, 98, 100, 102]
        result = run_rsi_mean_reversion_backtest(
            _candles(closes),
            RsiBacktestConfig(
                rsi_period=3,
                buy_below=30,
                sell_above=55,
                fee_rate=0,
                slippage_bps=0,
            ),
        )

        self.assertEqual([trade.side for trade in result.trades], ["BUY", "SELL"])
        self.assertGreater(result.final_equity, 1_000)

    def test_rejects_crossed_thresholds(self) -> None:
        with self.assertRaises(ValueError):
            run_rsi_mean_reversion_backtest(
                _candles([100, 99, 98, 97, 98, 99]),
                RsiBacktestConfig(rsi_period=3, buy_below=60, sell_above=50),
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
