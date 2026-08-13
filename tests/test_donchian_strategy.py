from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.donchian_strategy import (
    DonchianBacktestConfig,
    run_donchian_breakout_backtest,
)
from okx_quant_lab.okx_public import Candle


class DonchianStrategyTest(unittest.TestCase):
    def test_buys_breakout_and_sells_breakdown(self) -> None:
        closes = [100, 100, 100, 100, 100, 105, 110, 115, 120, 110, 100, 95, 95]
        result = run_donchian_breakout_backtest(
            _candles(closes),
            DonchianBacktestConfig(
                entry_window=3,
                exit_window=2,
                fee_rate=0,
                slippage_bps=0,
                trade_fraction=1.0,
            ),
        )

        self.assertEqual([trade.side for trade in result.trades], ["BUY", "SELL"])
        self.assertGreater(result.final_equity, 1_000)

    def test_flat_market_never_trades(self) -> None:
        closes = [100.0] * 30
        result = run_donchian_breakout_backtest(
            _candles(closes),
            DonchianBacktestConfig(entry_window=5, exit_window=3),
        )

        self.assertEqual(result.trades, [])
        self.assertAlmostEqual(result.return_pct, 0.0)

    def test_fees_and_slippage_reduce_returns(self) -> None:
        closes = [100, 100, 100, 100, 100, 105, 110, 115, 120, 110, 100, 95, 95]
        config_free = DonchianBacktestConfig(
            entry_window=3, exit_window=2, fee_rate=0, slippage_bps=0, trade_fraction=1.0
        )
        config_costly = DonchianBacktestConfig(
            entry_window=3, exit_window=2, fee_rate=0.001, slippage_bps=10, trade_fraction=1.0
        )

        free = run_donchian_breakout_backtest(_candles(closes), config_free)
        costly = run_donchian_breakout_backtest(_candles(closes), config_costly)

        self.assertLess(costly.final_equity, free.final_equity)

    def test_rejects_bad_config(self) -> None:
        candles = _candles([100.0] * 30)
        with self.assertRaises(ValueError):
            run_donchian_breakout_backtest(
                candles, DonchianBacktestConfig(entry_window=0)
            )
        with self.assertRaises(ValueError):
            run_donchian_breakout_backtest(
                _candles([100.0] * 5), DonchianBacktestConfig(entry_window=20)
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
