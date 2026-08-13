from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.monitoring import (
    HOUR_MS,
    build_paper_status,
    check_candle_freshness,
    check_paper_state_caught_up,
    render_markdown_report,
)
from okx_quant_lab.okx_public import Candle
from okx_quant_lab.paper import PaperConfig, PaperState


class MonitoringTest(unittest.TestCase):
    def test_candle_freshness_flags_stale_data(self) -> None:
        candles = [_candle(1_700_000_000_000, 100)]
        check = check_candle_freshness(
            "BTC-USDT",
            candles,
            now_ms=1_700_000_000_000 + 40 * HOUR_MS,
            max_age_hours=36,
        )

        self.assertFalse(check.passed)

    def test_paper_state_caught_up(self) -> None:
        candles = [_candle(1_700_000_000_000, 100)]
        state = PaperState(cash=1000, asset=0, last_timestamp_ms=1_700_000_000_000, fills=[])

        check = check_paper_state_caught_up(state, candles)

        self.assertTrue(check.passed)

    def test_render_markdown_report(self) -> None:
        candles = [_candle(1_700_000_000_000, 100)]
        state = PaperState(cash=1000, asset=0, last_timestamp_ms=1_700_000_000_000, fills=[])
        status = build_paper_status("BTC-USDT", state, candles, PaperConfig(inst_id="BTC-USDT"))
        check = check_paper_state_caught_up(state, candles)

        report = render_markdown_report("Report", 1_700_000_000_000, [check], status)

        self.assertIn("# Report", report)
        self.assertIn("PASS", report)
        self.assertIn("Paper Status", report)


def _candle(timestamp_ms: int, close: float) -> Candle:
    return Candle(
        timestamp_ms=timestamp_ms,
        open=close,
        high=close,
        low=close,
        close=close,
        volume_base=1.0,
        volume_quote=close,
        confirmed=True,
    )


if __name__ == "__main__":
    unittest.main()
