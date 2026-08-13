from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.grid_paper import GridPaperConfig, new_grid_paper_state, run_grid_paper_session
from okx_quant_lab.monitoring import (
    build_grid_paper_status,
    check_grid_price_in_range,
    check_grid_state_caught_up,
    render_grid_markdown_report,
)
from okx_quant_lab.okx_public import Candle


class GridMonitoringTest(unittest.TestCase):
    def test_caught_up_check_passes_after_session(self) -> None:
        config = _config()
        candles = _candles([100, 95, 100])
        state = run_grid_paper_session(candles, new_grid_paper_state(config, 100.0), config)

        self.assertTrue(check_grid_state_caught_up(state, candles).passed)

        more = candles + _candles([100], start_index=3)
        self.assertFalse(check_grid_state_caught_up(state, more).passed)

    def test_range_check_flags_price_below_range(self) -> None:
        config = _config()  # range 10% around 100 -> 90..110
        state = new_grid_paper_state(config, 100.0)

        inside = check_grid_price_in_range(state, _candles([100]))
        self.assertTrue(inside.passed)

        below = check_grid_price_in_range(state, _candles([80]))
        self.assertFalse(below.passed)
        self.assertIn("BELOW", below.message)

        above = check_grid_price_in_range(state, _candles([120]))
        self.assertTrue(above.passed)
        self.assertIn("idle", above.message)

    def test_status_and_report_expose_realized_versus_equity(self) -> None:
        config = _config()
        candles = _candles([100, 95, 88, 88])
        state = run_grid_paper_session(candles, new_grid_paper_state(config, 100.0), config)

        status = build_grid_paper_status("SOL-USDT", state, candles, config)
        self.assertEqual(status.grid_count, config.grid_count)
        self.assertGreater(status.open_slots, 0)
        self.assertLess(status.equity, config.initial_cash)

        report = render_grid_markdown_report(
            title="grid report",
            generated_at_ms=candles[-1].timestamp_ms,
            checks=[check_grid_price_in_range(state, candles)],
            grid_status=status,
        )
        self.assertIn("# grid report", report)
        self.assertIn("Open slots", report)
        self.assertIn("Realized profit", report)
        self.assertIn("not a trade instruction", report)


def _config() -> GridPaperConfig:
    return GridPaperConfig(
        inst_id="SOL-USDT",
        range_pct=10.0,
        grid_count=4,
        initial_cash=1_000.0,
        fee_rate=0.001,
    )


def _candles(closes: list[float], start_index: int = 0) -> list[Candle]:
    candles = []
    previous = closes[0]
    for offset, close in enumerate(closes):
        candles.append(
            Candle(
                timestamp_ms=1_700_000_000_000 + (start_index + offset) * 3_600_000,
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
