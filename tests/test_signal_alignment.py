from __future__ import annotations

import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.backtest import sma_wants_long
from okx_quant_lab.dry_run import sma_signal
from okx_quant_lab.okx_public import Candle
from okx_quant_lab.paper import PaperConfig, new_paper_state, run_paper_session


def _make_candles(closes: list[float]) -> list[Candle]:
    """Synthetic ascending candles where open != close on every bar, so any
    fill-at-close (or signal-from-open) bug is distinguishable from the
    open-fill convention this suite locks down."""
    candles = []
    for index, close in enumerate(closes):
        open_ = close - 0.4
        candles.append(
            Candle(
                timestamp_ms=1_700_000_000_000 + index * 60_000,
                open=open_,
                high=max(open_, close) + 0.5,
                low=min(open_, close) - 0.5,
                close=close,
                volume_base=1.0,
                volume_quote=open_ + close,
                confirmed=True,
            )
        )
    return candles


def _sine_closes(count: int = 60) -> list[float]:
    """A slow oscillation that crosses the SMA windows several times, so both
    LONG and CASH regimes (and the flips between them) are exercised."""
    return [round(100 + 10 * math.sin(index / 4.0), 2) for index in range(count)]


class SignalAlignmentLockTest(unittest.TestCase):
    """Locks the dry-run vs backtest signal alignment so nobody 'fixes' it.

    WHY THIS EXISTS (2026-08-13): a code review misdiagnosed
    dry_run.sma_signal as off-by-one relative to the backtest and proposed a
    'fix' that would have introduced a one-bar lag in the live path. The
    current alignment is CORRECT:

    - backtest/paper decide at index i from the closes STRICTLY BEFORE i
      (sma_wants_long) and fill at candles[i].open;
    - dry-run computes from all closed candles INCLUDING the latest (index t)
      and executes now, i.e. at approximately the next open (index t+1).

    Both sides therefore fill at the same next open, and
    sma_signal(candles[:t+1]) must equal the backtest decision at index t+1,
    not at index t. If one of these tests starts failing after a change to
    sma_signal or sma_wants_long, the change re-introduced the lag (or a
    lookahead) — revert it, do not update the test.
    """

    CONFIGS = (
        PaperConfig(inst_id="TEST-USDT", fast_window=5, slow_window=12),
        PaperConfig(inst_id="TEST-USDT", fast_window=3, slow_window=8),
    )

    def test_dry_run_signal_equals_backtest_decision_at_next_index(self) -> None:
        closes = _sine_closes()
        candles = _make_candles(closes)

        for config in self.CONFIGS:
            with self.subTest(fast=config.fast_window, slow=config.slow_window):
                decisions = sma_wants_long(
                    closes, config.fast_window, config.slow_window
                )
                signals = []
                for t in range(config.slow_window - 1, len(candles) - 1):
                    signal = sma_signal(candles[: t + 1], config)
                    signals.append(signal)
                    wants = decisions[t + 1]
                    self.assertIsNotNone(
                        wants,
                        f"backtest decision must be warmed up at index {t + 1}",
                    )
                    self.assertEqual(
                        signal,
                        "LONG" if wants else "CASH",
                        f"dry-run signal at t={t} must equal the backtest "
                        f"decision at index {t + 1} (both fill at the same "
                        "next open)",
                    )
                # Guard against a degenerate series making the loop vacuous:
                # the tested range must exercise both regimes.
                self.assertIn("LONG", signals)
                self.assertIn("CASH", signals)

    def test_one_bar_lagged_alignment_does_not_hold(self) -> None:
        """The misdiagnosed 'fix' aligned sma_signal(candles[:t+1]) with the
        backtest decision at index t (one bar late). That alignment must NOT
        hold everywhere on a series with crossovers — if it ever starts
        holding for every t, this suite has gone vacuous and can no longer
        catch the lag being re-introduced."""
        closes = _sine_closes()
        candles = _make_candles(closes)

        for config in self.CONFIGS:
            with self.subTest(fast=config.fast_window, slow=config.slow_window):
                decisions = sma_wants_long(
                    closes, config.fast_window, config.slow_window
                )
                lag_mismatches = 0
                for t in range(config.slow_window, len(candles) - 1):
                    signal = sma_signal(candles[: t + 1], config)
                    if signal != ("LONG" if decisions[t] else "CASH"):
                        lag_mismatches += 1
                self.assertGreater(
                    lag_mismatches,
                    0,
                    "the lagged alignment matched everywhere; the series no "
                    "longer discriminates correct from off-by-one alignment",
                )

    def test_paper_session_fills_at_candle_open_on_decision_flip(self) -> None:
        """Paper mirrors the backtest convention: decide at index i from
        closes strictly before i, fill at candles[i].open (never close)."""
        closes = [100.0 + i for i in range(20)] + [119.0 - i for i in range(20)]
        candles = _make_candles(closes)
        # slippage_bps=0 so the fill price is exactly the candle open.
        config = PaperConfig(
            inst_id="TEST-USDT", fast_window=5, slow_window=12, slippage_bps=0.0
        )

        state = run_paper_session(candles, new_paper_state(config), config)

        self.assertGreaterEqual(
            len(state.fills), 2, "expected the up-then-down series to flip"
        )
        self.assertEqual(state.fills[0].side, "BUY")
        self.assertEqual(state.fills[1].side, "SELL")

        by_timestamp = {candle.timestamp_ms: candle for candle in candles}
        for fill in state.fills:
            candle = by_timestamp[fill.timestamp_ms]
            self.assertNotEqual(
                candle.open, candle.close, "test candle must discriminate"
            )
            self.assertEqual(
                fill.price,
                candle.open,
                f"{fill.side} fill must land at the open of the decision "
                "candle, not its close",
            )

        # The BUY must land where the backtest decision sequence first turns
        # LONG — the same convention sma_wants_long encodes.
        decisions = sma_wants_long(closes, config.fast_window, config.slow_window)
        first_long = next(i for i, wants in enumerate(decisions) if wants)
        self.assertEqual(
            state.fills[0].timestamp_ms, candles[first_long].timestamp_ms
        )


if __name__ == "__main__":
    unittest.main()
