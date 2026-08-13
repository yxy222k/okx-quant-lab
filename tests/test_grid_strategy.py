from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.grid_strategy import (
    GridBacktestConfig,
    grid_config_from_reference,
    run_grid_backtest,
)
from okx_quant_lab.okx_public import Candle


class GridStrategyTest(unittest.TestCase):
    def test_round_trip_captures_one_grid_step(self) -> None:
        # Levels are [90, 100, 110]: slot 0 buys at 90, slot 1 buys at 100.
        config = GridBacktestConfig(
            lower_price=90,
            upper_price=110,
            grid_count=2,
            initial_cash=1_000,
            fee_rate=0,
        )
        candles = [
            _candle(0, open=105, high=105, low=99, close=100),
            _candle(1, open=100, high=111, low=100, close=110),
        ]

        result = run_grid_backtest(candles, config)

        self.assertEqual([fill.side for fill in result.fills], ["BUY", "SELL"])
        self.assertEqual(result.round_trips, 1)
        # Slot 1 spends 500 at 100 and sells at 110: profit is 50.
        self.assertAlmostEqual(result.realized_profit, 50.0)
        self.assertAlmostEqual(result.final_equity, 1_050.0)
        self.assertEqual(result.open_slots, 0)

    def test_fees_are_charged_on_both_sides(self) -> None:
        config = GridBacktestConfig(
            lower_price=90,
            upper_price=110,
            grid_count=2,
            initial_cash=1_000,
            fee_rate=0.001,
        )
        candles = [
            _candle(0, open=105, high=105, low=99, close=100),
            _candle(1, open=100, high=111, low=100, close=110),
        ]

        result = run_grid_backtest(candles, config)

        buy, sell = result.fills
        self.assertAlmostEqual(buy.fee, 0.5)
        self.assertGreater(sell.fee, 0)
        self.assertLess(result.realized_profit, 50.0)

    def test_downtrend_fills_all_slots_and_traps_inventory(self) -> None:
        config = GridBacktestConfig(
            lower_price=90,
            upper_price=110,
            grid_count=2,
            initial_cash=1_000,
            fee_rate=0,
        )
        candles = [
            _candle(0, open=105, high=105, low=95, close=95),
            _candle(1, open=95, high=95, low=80, close=80),
            _candle(2, open=80, high=82, low=78, close=80),
        ]

        result = run_grid_backtest(candles, config)

        self.assertEqual(result.round_trips, 0)
        self.assertEqual(result.open_slots, 2)
        self.assertLess(result.unrealized_pnl, 0)
        self.assertLess(result.final_equity, 1_000)
        self.assertEqual(result.candles_below_range, 2)

    def test_never_buys_above_the_market(self) -> None:
        config = GridBacktestConfig(
            lower_price=90,
            upper_price=110,
            grid_count=2,
            initial_cash=1_000,
            fee_rate=0,
        )
        candles = [
            _candle(0, open=85, high=120, low=85, close=120),
            _candle(1, open=120, high=125, low=120, close=125),
        ]

        result = run_grid_backtest(candles, config)

        self.assertEqual(result.fills, [])
        self.assertEqual(result.open_slots, 0)

    def test_slippage_worsens_fill_prices(self) -> None:
        config = GridBacktestConfig(
            lower_price=90,
            upper_price=110,
            grid_count=2,
            initial_cash=1_000,
            fee_rate=0,
            slippage_bps=100,
        )
        candles = [
            _candle(0, open=105, high=105, low=99, close=100),
            _candle(1, open=100, high=111, low=100, close=110),
        ]

        result = run_grid_backtest(candles, config)

        buy, sell = result.fills
        self.assertAlmostEqual(buy.price, 101.0)
        self.assertAlmostEqual(sell.price, 108.9)

    def test_rejects_bad_configs(self) -> None:
        candles = [_candle(0, open=100, high=100, low=100, close=100)]
        with self.assertRaises(ValueError):
            run_grid_backtest(candles, GridBacktestConfig(lower_price=110, upper_price=90))
        with self.assertRaises(ValueError):
            run_grid_backtest(
                candles,
                GridBacktestConfig(lower_price=90, upper_price=110, grid_count=1),
            )
        with self.assertRaises(ValueError):
            run_grid_backtest([], GridBacktestConfig(lower_price=90, upper_price=110))

    def test_grid_config_from_reference(self) -> None:
        config = grid_config_from_reference(reference_price=100, range_pct=15)

        self.assertAlmostEqual(config.lower_price, 85.0)
        self.assertAlmostEqual(config.upper_price, 115.0)


def _candle(index: int, open: float, high: float, low: float, close: float) -> Candle:
    return Candle(
        timestamp_ms=1_700_000_000_000 + index * 3_600_000,
        open=open,
        high=high,
        low=low,
        close=close,
        volume_base=1.0,
        volume_quote=close,
        confirmed=True,
    )


if __name__ == "__main__":
    unittest.main()
