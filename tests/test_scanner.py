from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.backtest import BacktestConfig
from okx_quant_lab.okx_public import Candle
from okx_quant_lab.risk import RiskLimits
from okx_quant_lab.scanner import scan_symbols


class ScannerTest(unittest.TestCase):
    def test_scan_symbols_ranks_by_return(self) -> None:
        rows = scan_symbols(
            {
                "DOWN-USDT": _candles([110, 109, 108, 107, 106, 105, 104, 103]),
                "UP-USDT": _candles([100, 101, 102, 103, 104, 105, 106, 107]),
            },
            BacktestConfig(fast_window=2, slow_window=3, fee_rate=0.001),
            RiskLimits(max_drawdown_pct=-50, min_trades=0, max_exposure_pct=100),
        )

        self.assertEqual(len(rows), 2)
        self.assertGreaterEqual(rows[0].return_pct, rows[1].return_pct)


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
