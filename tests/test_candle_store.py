from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.candle_store import load_candles_csv, merge_candles, save_candles_csv
from okx_quant_lab.okx_public import Candle


class CandleStoreTest(unittest.TestCase):
    def test_round_trip_csv(self) -> None:
        candles = [
            Candle(
                timestamp_ms=2,
                open=101.0,
                high=102.0,
                low=100.0,
                close=101.5,
                volume_base=3.0,
                volume_quote=304.5,
                confirmed=True,
            ),
            Candle(
                timestamp_ms=1,
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume_base=2.0,
                volume_quote=201.0,
                confirmed=True,
            ),
        ]

        with tempfile.TemporaryDirectory(dir=ROOT) as dirname:
            path = Path(dirname) / "candles.csv"

            save_candles_csv(path, candles)
            loaded = load_candles_csv(path)

        self.assertEqual([candle.timestamp_ms for candle in loaded], [1, 2])
        self.assertEqual(loaded[0].close, 100.5)
        self.assertTrue(loaded[1].confirmed)

    def test_merge_candles_deduplicates_by_timestamp(self) -> None:
        older = Candle(
            timestamp_ms=1,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume_base=2.0,
            volume_quote=201.0,
            confirmed=True,
        )
        replacement = Candle(
            timestamp_ms=1,
            open=200.0,
            high=201.0,
            low=199.0,
            close=200.5,
            volume_base=3.0,
            volume_quote=601.5,
            confirmed=True,
        )
        newer = Candle(
            timestamp_ms=2,
            open=101.0,
            high=102.0,
            low=100.0,
            close=101.5,
            volume_base=3.0,
            volume_quote=304.5,
            confirmed=True,
        )

        candles = merge_candles([older], [newer, replacement])

        self.assertEqual([candle.timestamp_ms for candle in candles], [1, 2])
        self.assertEqual(candles[0].close, 200.5)


if __name__ == "__main__":
    unittest.main()
