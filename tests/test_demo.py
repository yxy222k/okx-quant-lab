from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.backtest import BacktestConfig
from okx_quant_lab.demo import (
    SAFETY_STATUS,
    build_safe_demo_report,
    render_demo_html,
    render_demo_markdown,
)
from okx_quant_lab.grid_strategy import grid_config_from_reference
from okx_quant_lab.okx_public import Candle
from okx_quant_lab.paper import PaperConfig, new_paper_state, run_paper_session


class DemoTest(unittest.TestCase):
    def test_build_safe_demo_report_uses_paper_mode(self) -> None:
        candles = _candles([100 + index for index in range(80)])
        paper_config = PaperConfig(inst_id="TEST-USDT", fast_window=5, slow_window=10)
        before = new_paper_state(paper_config)
        after = run_paper_session(candles, before, paper_config)

        report = build_safe_demo_report(
            inst_id="TEST-USDT",
            bar="1H",
            candles=candles,
            paper_state_before=before,
            paper_state_after=after,
            backtest_config=BacktestConfig(fast_window=5, slow_window=10),
            paper_config=paper_config,
        )

        self.assertTrue(report.safety.allowed)
        self.assertGreater(report.summary.candle_count, 0)
        self.assertGreaterEqual(report.summary.new_paper_fills, 0)

    def test_render_reports_include_required_safety_status(self) -> None:
        candles = _candles([100 + index for index in range(80)])
        paper_config = PaperConfig(inst_id="TEST-USDT", fast_window=5, slow_window=10)
        before = new_paper_state(paper_config)
        after = run_paper_session(candles, before, paper_config)
        report = build_safe_demo_report(
            inst_id="TEST-USDT",
            bar="1H",
            candles=candles,
            paper_state_before=before,
            paper_state_after=after,
            backtest_config=BacktestConfig(fast_window=5, slow_window=10),
            paper_config=paper_config,
        )

        markdown = render_demo_markdown(report, 1_700_000_000_000)
        html = render_demo_html(report, 1_700_000_000_000)

        self.assertIn(SAFETY_STATUS, markdown)
        self.assertIn(SAFETY_STATUS, html)
        self.assertIn("Final Equity", html)

    def test_report_includes_grid_section_when_configured(self) -> None:
        candles = _candles([100 + index for index in range(80)])
        paper_config = PaperConfig(inst_id="TEST-USDT", fast_window=5, slow_window=10)
        before = new_paper_state(paper_config)
        after = run_paper_session(candles, before, paper_config)

        report = build_safe_demo_report(
            inst_id="TEST-USDT",
            bar="1H",
            candles=candles,
            paper_state_before=before,
            paper_state_after=after,
            backtest_config=BacktestConfig(fast_window=5, slow_window=10),
            paper_config=paper_config,
            grid_config=grid_config_from_reference(candles[0].open, range_pct=15.0),
        )

        self.assertIsNotNone(report.grid)
        markdown = render_demo_markdown(report, 1_700_000_000_000)
        html = render_demo_html(report, 1_700_000_000_000)
        self.assertIn("## Grid Strategy Backtest", markdown)
        self.assertIn("Grid Strategy Backtest", html)
        self.assertIn("Unrealized inventory PnL", markdown)

    def test_report_omits_grid_section_by_default(self) -> None:
        candles = _candles([100 + index for index in range(80)])
        paper_config = PaperConfig(inst_id="TEST-USDT", fast_window=5, slow_window=10)
        before = new_paper_state(paper_config)
        after = run_paper_session(candles, before, paper_config)

        report = build_safe_demo_report(
            inst_id="TEST-USDT",
            bar="1H",
            candles=candles,
            paper_state_before=before,
            paper_state_after=after,
            backtest_config=BacktestConfig(fast_window=5, slow_window=10),
            paper_config=paper_config,
        )

        self.assertIsNone(report.grid)
        self.assertNotIn("Grid Strategy Backtest", render_demo_markdown(report, 0))


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
