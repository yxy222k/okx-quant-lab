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

    def test_empty_map_returns_empty_list(self) -> None:
        rows = scan_symbols({}, _config(), _permissive_limits())

        self.assertEqual(rows, [])

    def test_ranks_multiple_symbols_by_return_desc(self) -> None:
        rows = scan_symbols(
            {
                "CRASH-USDT": _candles([100, 101, 102, 103, 104, 50, 50, 50]),
                "FLAT-USDT": _candles([100] * 8),
                "UP-USDT": _candles([100, 101, 102, 103, 104, 105, 106, 107]),
            },
            _config(),
            _permissive_limits(),
        )

        self.assertEqual(
            [row.inst_id for row in rows],
            ["UP-USDT", "FLAT-USDT", "CRASH-USDT"],
        )
        # UP buys and rides the trend; FLAT never crosses so sits in cash;
        # CRASH buys the ramp and sells after the collapse.
        self.assertGreater(rows[0].return_pct, 0.0)
        self.assertEqual(rows[1].return_pct, 0.0)
        self.assertLess(rows[2].return_pct, 0.0)
        returns = [row.return_pct for row in rows]
        self.assertEqual(returns, sorted(returns, reverse=True))

    def test_ties_keep_alphabetical_order_regardless_of_insertion(self) -> None:
        flat = [100] * 8
        rows = scan_symbols(
            {
                # Inserted in reverse-alphabetical order on purpose: identical
                # candles give identical returns, and the stable sort must fall
                # back to the alphabetical iteration order of the input map.
                "ZZZ-USDT": _candles(flat),
                "MMM-USDT": _candles(flat),
                "AAA-USDT": _candles(flat),
            },
            _config(),
            _permissive_limits(),
        )

        self.assertEqual(len({row.return_pct for row in rows}), 1)
        self.assertEqual(
            [row.inst_id for row in rows],
            ["AAA-USDT", "MMM-USDT", "ZZZ-USDT"],
        )

    def test_row_fields_reflect_per_symbol_backtest(self) -> None:
        rows = scan_symbols(
            {
                "FLAT-USDT": _candles([100] * 8),
                "UP-USDT": _candles([100, 101, 102, 103, 104, 105, 106, 107]),
            },
            _config(),
            _permissive_limits(),
        )
        by_id = {row.inst_id: row for row in rows}

        self.assertEqual(by_id["UP-USDT"].candles, 8)
        self.assertEqual(by_id["FLAT-USDT"].candles, 8)
        # UP crosses once (fast MA > slow MA from index 3) and never exits:
        # exactly one BUY trade, exposed for 5 of 8 equity points.
        self.assertEqual(by_id["UP-USDT"].trades, 1)
        self.assertAlmostEqual(by_id["UP-USDT"].exposure_pct, 62.5)
        # FLAT never trades and never holds the asset.
        self.assertEqual(by_id["FLAT-USDT"].trades, 0)
        self.assertEqual(by_id["FLAT-USDT"].exposure_pct, 0.0)
        # Buy-and-hold on a flat series loses exactly the round-trip fees.
        self.assertAlmostEqual(
            by_id["FLAT-USDT"].buy_hold_return_pct, (0.999**2 - 1) * 100
        )

    def test_passed_flag_applies_limits_per_symbol(self) -> None:
        candle_map = {
            "FLAT-USDT": _candles([100] * 8),
            "UP-USDT": _candles([100, 101, 102, 103, 104, 105, 106, 107]),
        }
        limits = RiskLimits(max_drawdown_pct=-50, min_trades=1, max_exposure_pct=100)

        rows = scan_symbols(candle_map, _config(), limits)
        by_id = {row.inst_id: row for row in rows}

        # UP makes its 1 trade and passes; FLAT makes 0 trades and fails the
        # min_trades limit — the flag is per symbol, not global.
        self.assertTrue(by_id["UP-USDT"].passed)
        self.assertFalse(by_id["FLAT-USDT"].passed)

    def test_drawdown_breach_marks_symbol_failed(self) -> None:
        rows = scan_symbols(
            {"CRASH-USDT": _candles([100, 101, 102, 103, 104, 50, 50, 50])},
            _config(),
            RiskLimits(max_drawdown_pct=-10, min_trades=0, max_exposure_pct=100),
        )

        self.assertEqual(len(rows), 1)
        self.assertLess(rows[0].max_drawdown_pct, -10)
        self.assertFalse(rows[0].passed)

    def test_insufficient_candles_for_any_symbol_raises(self) -> None:
        with self.assertRaises(ValueError):
            scan_symbols(
                {
                    "OK-USDT": _candles([100, 101, 102, 103, 104, 105, 106, 107]),
                    "SHORT-USDT": _candles([100, 101, 102]),
                },
                _config(),
                _permissive_limits(),
            )


def _config() -> BacktestConfig:
    return BacktestConfig(fast_window=2, slow_window=3, fee_rate=0.001)


def _permissive_limits() -> RiskLimits:
    return RiskLimits(max_drawdown_pct=-100, min_trades=0, max_exposure_pct=100)


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
