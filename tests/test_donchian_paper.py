from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.donchian_paper import (
    DonchianPaperConfig,
    donchian_paper_equity,
    load_paper_state,
    new_donchian_paper_state,
    run_donchian_paper_session,
    save_paper_state,
)
from okx_quant_lab.okx_public import Candle


class DonchianPaperTest(unittest.TestCase):
    def test_resume_matches_single_run(self) -> None:
        config = _config()
        candles = _breakout_candles()

        once = run_donchian_paper_session(
            candles, new_donchian_paper_state(config), config
        )

        resumed = new_donchian_paper_state(config)
        resumed = run_donchian_paper_session(candles[:8], resumed, config)
        resumed = run_donchian_paper_session(candles, resumed, config)

        self.assertEqual(once, resumed)

    def test_rerun_on_same_candles_adds_nothing(self) -> None:
        config = _config()
        candles = _breakout_candles()

        state = run_donchian_paper_session(
            candles, new_donchian_paper_state(config), config
        )
        rerun = run_donchian_paper_session(candles, state, config)

        self.assertEqual(state, rerun)

    def test_trades_breakout_and_persists(self) -> None:
        config = _config()
        candles = _breakout_candles()

        state = run_donchian_paper_session(
            candles, new_donchian_paper_state(config), config
        )
        self.assertEqual([fill.side for fill in state.fills], ["BUY", "SELL"])

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "donchian_state.json"
            save_paper_state(path, state)
            loaded = load_paper_state(path)

        self.assertEqual(state, loaded)
        equity = donchian_paper_equity(loaded, candles[-1].close, config)
        self.assertGreater(equity, 0)


def _config() -> DonchianPaperConfig:
    return DonchianPaperConfig(
        inst_id="SOL-USDT",
        entry_window=3,
        exit_window=2,
        fee_rate=0.001,
        slippage_bps=2.0,
        trade_fraction=0.5,
    )


def _breakout_candles() -> list[Candle]:
    closes = [100, 100, 100, 100, 100, 105, 110, 115, 120, 110, 100, 95, 95]
    return _candles(closes)


def _candles(closes: list[float]) -> list[Candle]:
    candles = []
    previous = closes[0]
    for index, close in enumerate(closes):
        candles.append(
            Candle(
                timestamp_ms=1_700_000_000_000 + index * 3_600_000,
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
