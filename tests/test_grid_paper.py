from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.grid_paper import (
    GridPaperConfig,
    grid_paper_equity,
    load_grid_paper_state,
    new_grid_paper_state,
    open_slot_count,
    run_grid_paper_session,
    save_grid_paper_state,
)
from okx_quant_lab.okx_public import Candle


class GridPaperTest(unittest.TestCase):
    def test_resume_matches_single_run(self) -> None:
        config = _config()
        candles = _oscillating_candles(20)

        once = run_grid_paper_session(candles, new_grid_paper_state(config, 100.0), config)

        resumed = new_grid_paper_state(config, 100.0)
        resumed = run_grid_paper_session(candles[:7], resumed, config)
        resumed = run_grid_paper_session(candles, resumed, config)

        self.assertEqual(once, resumed)

    def test_rerun_on_same_candles_adds_nothing(self) -> None:
        config = _config()
        candles = _oscillating_candles(20)

        state = run_grid_paper_session(candles, new_grid_paper_state(config, 100.0), config)
        rerun = run_grid_paper_session(candles, state, config)

        self.assertEqual(state, rerun)

    def test_state_survives_save_and_load(self) -> None:
        config = _config()
        candles = _oscillating_candles(20)
        state = run_grid_paper_session(candles, new_grid_paper_state(config, 100.0), config)
        self.assertGreater(len(state.fills), 0)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "grid_state.json"
            save_grid_paper_state(path, state)
            loaded = load_grid_paper_state(path)

        self.assertEqual(state, loaded)

    def test_grid_trades_and_banks_realized_profit(self) -> None:
        config = _config(fee_rate=0)
        candles = _oscillating_candles(20)

        state = run_grid_paper_session(candles, new_grid_paper_state(config, 100.0), config)

        self.assertGreater(state.realized_profit, 0)
        sides = {fill.side for fill in state.fills}
        self.assertEqual(sides, {"BUY", "SELL"})

    def test_downtrend_traps_slots(self) -> None:
        config = _config(fee_rate=0)
        closes = [100 - 3 * step for step in range(12)]  # 100 down to 67
        candles = _candles(closes)

        state = run_grid_paper_session(candles, new_grid_paper_state(config, 100.0), config)

        self.assertEqual(open_slot_count(state), config.grid_count // 2)
        equity = grid_paper_equity(state, candles[-1].close, config)
        self.assertLess(equity, config.initial_cash)

    def test_rejects_bad_reference_price(self) -> None:
        with self.assertRaises(ValueError):
            new_grid_paper_state(_config(), 0.0)


def _config(fee_rate: float = 0.001) -> GridPaperConfig:
    return GridPaperConfig(
        inst_id="SOL-USDT",
        range_pct=10.0,
        grid_count=4,
        initial_cash=1_000.0,
        fee_rate=fee_rate,
    )


def _oscillating_candles(count: int) -> list[Candle]:
    closes = [100 if index % 2 == 0 else 91 for index in range(count)]
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
