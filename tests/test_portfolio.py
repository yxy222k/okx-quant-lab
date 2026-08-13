from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.backtest import BacktestConfig
from okx_quant_lab.market_math import max_drawdown_pct
from okx_quant_lab.okx_public import Candle
from okx_quant_lab.portfolio import run_equal_weight_portfolio

BASE_TS = 1_700_000_000_000
HOUR_MS = 3_600_000


class PortfolioTest(unittest.TestCase):
    def test_equal_weight_portfolio_combines_legs(self) -> None:
        result = run_equal_weight_portfolio(
            candle_map={
                "A-USDT": _candles([100, 101, 102, 103, 104, 105, 106, 107]),
                "B-USDT": _candles([100, 99, 98, 97, 96, 95, 94, 93]),
            },
            base_config=BacktestConfig(fast_window=2, slow_window=3),
            total_cash=1_000,
        )

        self.assertEqual(len(result.legs), 2)
        self.assertEqual(len(result.equity_curve), 8)
        self.assertGreater(result.final_equity, 0)

    def test_rejects_empty_portfolio(self) -> None:
        with self.assertRaises(ValueError):
            run_equal_weight_portfolio({}, BacktestConfig(), total_cash=1_000)

    def test_portfolio_equity_is_sum_of_leg_equities_on_common_timestamps(self) -> None:
        # Leg A spans hour indices 0..9, leg B spans 2..11: overlapping but not
        # identical ranges, so the portfolio curve must cover exactly 2..9.
        result = run_equal_weight_portfolio(
            candle_map={
                "A-USDT": _candles(
                    [100, 101, 102, 103, 104, 105, 106, 107, 108, 109]
                ),
                "B-USDT": _candles(
                    [50, 52, 51, 53, 55, 54, 56, 58, 57, 59], start_index=2
                ),
            },
            base_config=BacktestConfig(fast_window=2, slow_window=3),
            total_cash=1_000,
        )

        expected_timestamps = [BASE_TS + index * HOUR_MS for index in range(2, 10)]
        self.assertEqual(
            [point.timestamp_ms for point in result.equity_curve],
            expected_timestamps,
        )

        # Each leg received an equal share of the cash.
        for leg in result.legs:
            self.assertAlmostEqual(leg.result.config.initial_cash, 500.0)

        leg_equity_maps = [
            {point.timestamp_ms: point.equity for point in leg.result.equity_curve}
            for leg in result.legs
        ]
        for point in result.equity_curve:
            self.assertAlmostEqual(
                point.equity,
                sum(equity_map[point.timestamp_ms] for equity_map in leg_equity_maps),
                msg=f"portfolio equity at {point.timestamp_ms} is not the leg sum",
            )
        self.assertAlmostEqual(result.final_equity, result.equity_curve[-1].equity)

    def test_rejects_legs_with_no_overlapping_timestamps(self) -> None:
        with self.assertRaisesRegex(ValueError, "overlap"):
            run_equal_weight_portfolio(
                candle_map={
                    "A-USDT": _candles([100, 101, 102, 103, 104, 105]),
                    "B-USDT": _candles(
                        [50, 51, 52, 53, 54, 55], start_index=100
                    ),
                },
                base_config=BacktestConfig(fast_window=2, slow_window=3),
                total_cash=1_000,
            )

    def test_return_and_drawdown_are_computed_from_summed_curve(self) -> None:
        total_cash = 1_000.0
        # Rising then dipping closes: both legs go long after warmup and the
        # summed curve has a genuine peak-to-trough drop, so the drawdown
        # comparison is not a trivial 0 == 0.
        result = run_equal_weight_portfolio(
            candle_map={
                "A-USDT": _candles(
                    [100, 101, 102, 103, 104, 90, 80, 95, 110, 120]
                ),
                "B-USDT": _candles(
                    [200, 202, 204, 206, 208, 180, 170, 190, 220, 230],
                    start_index=1,
                ),
            },
            base_config=BacktestConfig(fast_window=2, slow_window=3),
            total_cash=total_cash,
        )

        # Rebuild the summed curve independently from the legs, restricted to
        # the timestamps the portfolio reports.
        leg_equity_maps = [
            {point.timestamp_ms: point.equity for point in leg.result.equity_curve}
            for leg in result.legs
        ]
        summed_equities = [
            sum(equity_map[point.timestamp_ms] for equity_map in leg_equity_maps)
            for point in result.equity_curve
        ]

        expected_return_pct = (summed_equities[-1] / total_cash - 1) * 100
        self.assertAlmostEqual(result.return_pct, expected_return_pct)
        self.assertAlmostEqual(
            result.max_drawdown_pct, max_drawdown_pct(summed_equities)
        )
        self.assertLess(result.max_drawdown_pct, 0.0)


def _candles(closes: list[float], start_index: int = 0) -> list[Candle]:
    return [
        Candle(
            timestamp_ms=BASE_TS + (start_index + index) * HOUR_MS,
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
