from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.backtest import BacktestConfig, run_sma_backtest
from okx_quant_lab.okx_public import Candle
from okx_quant_lab.risk import RiskLimits, build_risk_report, compare_position_sizes


class RiskTest(unittest.TestCase):
    def test_build_risk_report_flags_limit_breaches(self) -> None:
        result = run_sma_backtest(
            _candles([100, 101, 102, 103, 104, 90, 89, 88, 87, 86]),
            BacktestConfig(fast_window=2, slow_window=3),
        )

        report = build_risk_report(
            result,
            RiskLimits(max_drawdown_pct=-1.0, min_trades=4, max_exposure_pct=10.0),
        )

        self.assertFalse(report.passed)
        self.assertTrue(report.notes)
        self.assertGreaterEqual(report.exposure_pct, 0)

    def test_compare_position_sizes_returns_one_row_per_fraction(self) -> None:
        rows = compare_position_sizes(
            candles=_candles([100, 101, 102, 103, 104, 103, 102, 101]),
            base_config=BacktestConfig(fast_window=2, slow_window=3),
            trade_fractions=[1.0, 0.5],
            limits=RiskLimits(max_drawdown_pct=-50.0, min_trades=1, max_exposure_pct=100.0),
        )

        self.assertEqual([row.trade_fraction for row in rows], [1.0, 0.5])
        self.assertEqual(len(rows), 2)


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
