from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.candle_visualization import (
    SAFETY_STATUS,
    candle_data_summary,
    render_candle_dashboard,
)


class CandleVisualizationTest(unittest.TestCase):
    def test_renders_local_dashboard_with_embedded_data(self) -> None:
        html = render_candle_dashboard(_sample_payload(), 1_700_000_000_000)

        self.assertIn("OKX Candle Visualizer", html)
        self.assertIn(SAFETY_STATUS, html)
        self.assertIn("priceCanvas", html)
        self.assertIn("BTC/USDT", html)

    def test_summary_reports_pair_returns(self) -> None:
        rows = candle_data_summary(_sample_payload())

        self.assertEqual(rows[0]["pair"], "BTC/USDT")
        self.assertEqual(rows[0]["candles"], 2)
        self.assertAlmostEqual(rows[0]["return_pct"], 1.0)

    def test_rejects_missing_pairs(self) -> None:
        with self.assertRaises(ValueError):
            render_candle_dashboard({"pairs": {}}, 1_700_000_000_000)


def _sample_payload() -> dict:
    return {
        "source": "test",
        "timeframe": "1h",
        "pairs": {
            "BTC/USDT": [
                {
                    "timestamp_ms": 1_700_000_000_000,
                    "time_utc": "2023-11-14T22:13:20+00:00",
                    "open": 100.0,
                    "high": 102.0,
                    "low": 99.0,
                    "close": 100.0,
                    "volume": 10.0,
                },
                {
                    "timestamp_ms": 1_700_003_600_000,
                    "time_utc": "2023-11-14T23:13:20+00:00",
                    "open": 100.0,
                    "high": 103.0,
                    "low": 100.0,
                    "close": 101.0,
                    "volume": 12.0,
                },
            ]
        },
    }


if __name__ == "__main__":
    unittest.main()
