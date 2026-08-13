from __future__ import annotations

from pathlib import Path
import math
import sys
import unittest
from dataclasses import replace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.backtest import (
    BacktestConfig,
    BacktestResult,
    EquityPoint,
    Trade,
    run_sma_backtest,
)
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


class ComparePositionSizesEquivalenceTest(unittest.TestCase):
    """compare_position_sizes signals once (sma_wants_long) and replays fills per
    trade fraction; every row must be indistinguishable from running the full
    run_sma_backtest with that fraction."""

    FRACTIONS = [1.0, 0.6, 0.25]
    LIMITS = RiskLimits(max_drawdown_pct=-6.0, min_trades=3, max_exposure_pct=60.0)

    def test_rows_match_full_backtest_per_fraction(self) -> None:
        candles = _wavy_candles(80)
        base = BacktestConfig(
            initial_cash=2_500.0,
            fast_window=3,
            slow_window=7,
            fee_rate=0.001,
            slippage_bps=5.0,
        )

        rows = compare_position_sizes(candles, base, self.FRACTIONS, self.LIMITS)

        self.assertEqual(len(rows), len(self.FRACTIONS))
        for row, fraction in zip(rows, self.FRACTIONS):
            expected = run_sma_backtest(candles, replace(base, trade_fraction=fraction))
            expected_report = build_risk_report(expected, self.LIMITS)

            self.assertEqual(row.trade_fraction, fraction)
            self.assertEqual(row.final_equity, expected.final_equity)
            self.assertEqual(row.return_pct, expected.return_pct)
            self.assertEqual(row.max_drawdown_pct, expected.max_drawdown_pct)
            self.assertEqual(row.trades, len(expected.trades))
            self.assertEqual(row.exposure_pct, expected_report.exposure_pct)
            self.assertEqual(row.passed, expected_report.passed)

        # Guard against a vacuous pass: the synthetic series must actually
        # generate trades, and sizing must actually change the outcome.
        self.assertGreaterEqual(rows[0].trades, 4)
        self.assertNotEqual(rows[0].final_equity, rows[-1].final_equity)

    def test_unsorted_candles_replay_like_the_sorted_backtest(self) -> None:
        # compare_position_sizes sorts defensively, mirroring run_sma_backtest:
        # feeding it reversed candles must reproduce the ascending backtest.
        candles = _wavy_candles(80)
        base = BacktestConfig(fast_window=3, slow_window=7, fee_rate=0.001)

        rows = compare_position_sizes(
            list(reversed(candles)), base, [0.5], self.LIMITS
        )
        expected = run_sma_backtest(candles, replace(base, trade_fraction=0.5))

        self.assertEqual(rows[0].final_equity, expected.final_equity)
        self.assertEqual(rows[0].return_pct, expected.return_pct)
        self.assertEqual(rows[0].max_drawdown_pct, expected.max_drawdown_pct)
        self.assertEqual(rows[0].trades, len(expected.trades))


class BuildRiskReportNotesTest(unittest.TestCase):
    """Each limit breach must produce exactly its own note; boundary values are
    not breaches (drawdown/exposure comparisons are strict)."""

    LIMITS = RiskLimits(max_drawdown_pct=-10.0, min_trades=4, max_exposure_pct=50.0)

    def test_clean_result_passes_with_no_notes(self) -> None:
        result = _fake_result(return_pct=8.0, max_drawdown_pct=-4.0)
        report = build_risk_report(result, self.LIMITS)

        self.assertTrue(report.passed)
        self.assertEqual(report.notes, [])
        self.assertEqual(report.return_pct, result.return_pct)
        self.assertEqual(report.max_drawdown_pct, result.max_drawdown_pct)
        self.assertEqual(report.trades, len(result.trades))
        self.assertAlmostEqual(report.return_over_drawdown, 2.0)
        self.assertAlmostEqual(report.exposure_pct, 20.0)

    def test_drawdown_breach_alone_yields_single_drawdown_note(self) -> None:
        report = build_risk_report(
            _fake_result(max_drawdown_pct=-10.01), self.LIMITS
        )

        self.assertFalse(report.passed)
        self.assertEqual(len(report.notes), 1)
        self.assertIn("drawdown", report.notes[0])
        self.assertIn("-10.01%", report.notes[0])
        self.assertIn("-10.00%", report.notes[0])

    def test_drawdown_at_exact_limit_is_not_a_breach(self) -> None:
        report = build_risk_report(
            _fake_result(max_drawdown_pct=-10.0), self.LIMITS
        )

        self.assertTrue(report.passed)
        self.assertEqual(report.notes, [])

    def test_too_few_trades_yields_single_trades_note(self) -> None:
        report = build_risk_report(_fake_result(trade_count=3), self.LIMITS)

        self.assertFalse(report.passed)
        self.assertEqual(len(report.notes), 1)
        self.assertIn("only 3 trades", report.notes[0])
        self.assertIn("minimum is 4", report.notes[0])

    def test_exposure_breach_alone_yields_single_exposure_note(self) -> None:
        report = build_risk_report(
            _fake_result(exposed_points=6), self.LIMITS
        )

        self.assertFalse(report.passed)
        self.assertEqual(len(report.notes), 1)
        self.assertIn("exposure 60.0%", report.notes[0])
        self.assertIn("limit 50.0%", report.notes[0])

    def test_exposure_at_exact_limit_is_not_a_breach(self) -> None:
        report = build_risk_report(
            _fake_result(exposed_points=5), self.LIMITS
        )

        self.assertTrue(report.passed)
        self.assertEqual(report.notes, [])
        self.assertAlmostEqual(report.exposure_pct, 50.0)

    def test_all_limits_breached_collects_notes_in_order(self) -> None:
        report = build_risk_report(
            _fake_result(max_drawdown_pct=-25.0, trade_count=1, exposed_points=9),
            self.LIMITS,
        )

        self.assertFalse(report.passed)
        self.assertEqual(len(report.notes), 3)
        self.assertIn("drawdown", report.notes[0])
        self.assertIn("only 1 trades", report.notes[1])
        self.assertIn("exposure", report.notes[2])

    def test_zero_drawdown_gives_zero_return_over_drawdown(self) -> None:
        report = build_risk_report(
            _fake_result(return_pct=8.0, max_drawdown_pct=0.0), self.LIMITS
        )

        self.assertEqual(report.return_over_drawdown, 0.0)

    def test_empty_equity_curve_reports_zero_exposure(self) -> None:
        report = build_risk_report(
            _fake_result(total_points=0, exposed_points=0), self.LIMITS
        )

        self.assertEqual(report.exposure_pct, 0.0)
        self.assertTrue(report.passed)


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


def _wavy_candles(count: int) -> list[Candle]:
    """Oscillating series (sine plus mild drift) so the SMA cross flips several
    times; open is the previous close, so fills differ from signal closes."""
    closes = [
        100.0 + 10.0 * math.sin(index / 4.0) + index * 0.05 for index in range(count)
    ]
    candles: list[Candle] = []
    previous_close = closes[0]
    for index, close in enumerate(closes):
        open_price = previous_close
        candles.append(
            Candle(
                timestamp_ms=1_700_000_000_000 + index * 3_600_000,
                open=open_price,
                high=max(open_price, close) + 0.5,
                low=min(open_price, close) - 0.5,
                close=close,
                volume_base=1.0,
                volume_quote=close,
                confirmed=True,
            )
        )
        previous_close = close
    return candles


def _fake_result(
    *,
    return_pct: float = 5.0,
    max_drawdown_pct: float = -2.0,
    trade_count: int = 4,
    exposed_points: int = 2,
    total_points: int = 10,
) -> BacktestResult:
    """Hand-built BacktestResult so each build_risk_report limit can be pushed
    over its edge independently. Exposure is exposed_points/total_points."""
    equity_curve = [
        EquityPoint(
            timestamp_ms=1_700_000_000_000 + index * 3_600_000,
            cash=0.0 if index < exposed_points else 1_000.0,
            asset=1.0 if index < exposed_points else 0.0,
            close=100.0,
            equity=1_000.0,
        )
        for index in range(total_points)
    ]
    trades = [
        Trade(
            timestamp_ms=1_700_000_000_000 + index * 3_600_000,
            side="BUY" if index % 2 == 0 else "SELL",
            price=100.0,
            quantity=1.0,
            fee=0.1,
            cash_after=0.0,
            asset_after=1.0,
        )
        for index in range(trade_count)
    ]
    return BacktestResult(
        config=BacktestConfig(fast_window=2, slow_window=3),
        trades=trades,
        equity_curve=equity_curve,
        final_equity=1_000.0 * (1 + return_pct / 100),
        return_pct=return_pct,
        buy_and_hold_return_pct=0.0,
        max_drawdown_pct=max_drawdown_pct,
    )


if __name__ == "__main__":
    unittest.main()
