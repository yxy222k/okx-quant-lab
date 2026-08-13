from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.lab_scoreboard import (
    LabScoreRules,
    MarketMetrics,
    render_lab_scoreboard_markdown,
    score_lab_strategy,
)


class LabScoreboardTest(unittest.TestCase):
    def test_passing_strategy(self) -> None:
        markets = [
            MarketMetrics("BTC-USDT", 2.0, -3.0, 12),
            MarketMetrics("ETH-USDT", 1.0, -4.0, 10),
            MarketMetrics("SOL-USDT", -0.5, -2.0, 8),
        ]

        score = score_lab_strategy("sma(20,50)", markets, LabScoreRules())

        self.assertEqual(score.decision, "PASS")
        self.assertAlmostEqual(score.avg_return_pct, 2.5 / 3)
        self.assertAlmostEqual(score.worst_drawdown_pct, -4.0)
        self.assertEqual(score.total_trades, 30)
        self.assertEqual(score.profitable_markets, 2)

    def test_deep_drawdown_rejects(self) -> None:
        markets = [
            MarketMetrics("BTC-USDT", 5.0, -12.0, 30),
            MarketMetrics("ETH-USDT", 4.0, -3.0, 30),
        ]

        score = score_lab_strategy("grid", markets, LabScoreRules())

        self.assertEqual(score.decision, "REJECT")
        failed = [check.name for check in score.checks if not check.passed]
        self.assertEqual(failed, ["worst drawdown"])

    def test_too_few_trades_rejects(self) -> None:
        markets = [MarketMetrics("BTC-USDT", 1.0, -1.0, 3)]

        score = score_lab_strategy("donchian", markets, LabScoreRules(min_total_trades=20))

        self.assertEqual(score.decision, "REJECT")

    def test_markdown_contains_decisions(self) -> None:
        passing = score_lab_strategy(
            "sma(20,50)",
            [MarketMetrics("BTC-USDT", 2.0, -3.0, 30)],
        )
        failing = score_lab_strategy(
            "rsi(14)",
            [MarketMetrics("BTC-USDT", -2.0, -9.0, 5)],
        )

        report = render_lab_scoreboard_markdown(
            [passing, failing], LabScoreRules(), 1_700_000_000_000
        )

        self.assertIn("| PASS | `sma(20,50)` |", report)
        self.assertIn("| REJECT | `rsi(14)` |", report)
        self.assertIn("permission to keep researching", report)

    def test_rejects_empty_markets(self) -> None:
        with self.assertRaises(ValueError):
            score_lab_strategy("sma", [])


if __name__ == "__main__":
    unittest.main()
