from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.okx_public import Candle
from okx_quant_lab.paper import (
    PaperConfig,
    load_paper_state,
    new_paper_state,
    run_paper_session,
    save_paper_state,
)


class PaperTest(unittest.TestCase):
    def test_paper_session_is_idempotent_for_same_candles(self) -> None:
        candles = _candles([100, 101, 102, 103, 104, 103, 102, 101])
        config = PaperConfig(inst_id="TEST-USDT", fast_window=2, slow_window=3)
        state = run_paper_session(candles, new_paper_state(config), config)
        fills_after_first_run = len(state.fills)

        state = run_paper_session(candles, state, config)

        self.assertEqual(len(state.fills), fills_after_first_run)
        self.assertEqual(state.last_timestamp_ms, candles[-1].timestamp_ms)

    def test_paper_state_round_trip(self) -> None:
        candles = _candles([100, 101, 102, 103, 104, 103, 102, 101])
        config = PaperConfig(inst_id="TEST-USDT", fast_window=2, slow_window=3)
        state = run_paper_session(candles, new_paper_state(config), config)

        with tempfile.TemporaryDirectory(dir=ROOT) as dirname:
            path = Path(dirname) / "state.json"
            save_paper_state(path, state)
            loaded = load_paper_state(path)

        self.assertEqual(loaded.cash, state.cash)
        self.assertEqual(loaded.asset, state.asset)
        self.assertEqual(len(loaded.fills), len(state.fills))


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
