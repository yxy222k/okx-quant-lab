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
from okx_quant_lab.portfolio import run_equal_weight_portfolio


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
