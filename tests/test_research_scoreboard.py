from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.research_scoreboard import (
    ResearchScoreRules,
    render_scoreboard_markdown,
    score_freqtrade_backtest,
    score_freqtrade_strategy,
)


class ResearchScoreboardTest(unittest.TestCase):
    def test_rejects_flat_strategy_even_when_it_is_best_available(self) -> None:
        score = score_freqtrade_strategy(
            "FlatStrategy",
            {
                "total_trades": 52,
                "profit_total": 0.0005,
                "profit_factor": 1.05,
                "max_drawdown_account": 0.003,
                "expectancy": 0.01,
                "results_per_pair": [
                    {"key": "BTC/USDT", "profit_total": -0.0004},
                    {"key": "ETH/USDT", "profit_total": 0.0004},
                    {"key": "SOL/USDT", "profit_total": 0.0005},
                    {"key": "TOTAL", "profit_total": 0.0005},
                ],
            },
        )

        self.assertEqual(score.decision, "REJECT")
        self.assertIn("minimum return", _failed_names(score))
        self.assertIn("profit factor", _failed_names(score))

    def test_passes_strategy_that_meets_all_rules(self) -> None:
        score = score_freqtrade_strategy(
            "BetterStrategy",
            {
                "total_trades": 80,
                "profit_total": 0.015,
                "profit_factor": 1.4,
                "max_drawdown_account": 0.02,
                "expectancy": 0.2,
                "results_per_pair": [
                    {"key": "BTC/USDT", "profit_total": 0.006},
                    {"key": "ETH/USDT", "profit_total": 0.004},
                    {"key": "SOL/USDT", "profit_total": 0.005},
                    {"key": "TOTAL", "profit_total": 0.015},
                ],
            },
        )

        self.assertEqual(score.decision, "PASS")

    def test_scores_freqtrade_backtest_sorted_by_return(self) -> None:
        scores = score_freqtrade_backtest(
            {
                "strategy": {
                    "Loser": {
                        "total_trades": 40,
                        "profit_total": -0.01,
                    },
                    "Winner": {
                        "total_trades": 40,
                        "profit_total": 0.01,
                    },
                }
            }
        )

        self.assertEqual([score.strategy for score in scores], ["Winner", "Loser"])

    def test_render_markdown_includes_decisions(self) -> None:
        scores = score_freqtrade_backtest(
            {
                "strategy": {
                    "TinyWinner": {
                        "total_trades": 40,
                        "profit_total": 0.0001,
                        "profit_factor": 1.01,
                        "max_drawdown_account": 0.01,
                        "expectancy": 0.01,
                        "results_per_pair": [
                            {"key": "BTC/USDT", "profit_total": 0.0001},
                        ],
                    }
                }
            }
        )

        markdown = render_scoreboard_markdown(
            scores,
            ResearchScoreRules(),
            "example.zip",
            1_700_000_000_000,
        )

        self.assertIn("REJECT", markdown)
        self.assertIn("TinyWinner", markdown)


def _failed_names(score) -> set[str]:
    return {check.name for check in score.checks if not check.passed}


if __name__ == "__main__":
    unittest.main()
