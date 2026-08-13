from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
for p in (str(SRC), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from okx_quant_lab.demo_grid import DemoGridConfig, new_demo_grid_state
from okx_quant_lab.okx_public import Candle
from reconcile_grids import _replay_window


def _candles(n: int, start_ms: int = 1_700_000_000_000, step_ms: int = 900_000):
    # Prices oscillate around 100 so the midpoint fallback has a clear target.
    return [
        Candle(
            timestamp_ms=start_ms + i * step_ms,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0 if i % 2 == 0 else 98.0,
            volume_base=1.0,
            volume_quote=100.0,
            confirmed=True,
        )
        for i in range(n)
    ]


def _state(deploy_ts: int):
    base = new_demo_grid_state(
        DemoGridConfig(inst_id="SOL-USDT", range_pct=10.0, grid_count=4), 100.0
    )
    return replace(base, deploy_timestamp_ms=deploy_ts)


class ReplayWindowTest(unittest.TestCase):
    def test_anchored_window_starts_strictly_after_deploy(self) -> None:
        candles = _candles(10)
        deploy_ts = candles[3].timestamp_ms
        window, anchored = _replay_window(candles, _state(deploy_ts), [], [90.0, 110.0])

        self.assertTrue(anchored)
        # Live skipped the deploy candle, so the replay starts at candle 4.
        self.assertEqual([c.timestamp_ms for c in window], [c.timestamp_ms for c in candles[4:]])

    def test_empty_anchored_window_is_none_not_empty_list(self) -> None:
        # Fresh deploy: deploy_timestamp_ms == the newest candle, nothing after.
        candles = _candles(5)
        deploy_ts = candles[-1].timestamp_ms
        window, anchored = _replay_window(candles, _state(deploy_ts), [], [90.0, 110.0])

        self.assertIsNone(window)  # must not be [] — that would crash run_grid_backtest
        self.assertTrue(anchored)

    def test_trimmed_deploy_candle_reports_insufficient_history(self) -> None:
        candles = _candles(10)
        # Deploy timestamp older than the earliest candle still on file.
        deploy_ts = candles[0].timestamp_ms - 900_000
        window, anchored = _replay_window(candles, _state(deploy_ts), [], [90.0, 110.0])

        self.assertIsNone(window)
        self.assertTrue(anchored)

    def test_legacy_state_falls_back_to_midpoint_inference(self) -> None:
        candles = _candles(10)
        window, anchored = _replay_window(candles, _state(0), [], [90.0, 110.0])

        self.assertFalse(anchored)
        # Midpoint 100.0: first candle (close 100) is the inferred deploy, so
        # the whole series replays (>= inclusive in the legacy path).
        self.assertEqual(len(window), len(candles))


if __name__ == "__main__":
    unittest.main()
