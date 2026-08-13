"""Lock the trigger semantics that differ across the three grid engines.

These differences are INTENTIONAL and the paper-vs-live optimism measurement
(eq_gap, exec_gap) depends on them. A refactor must not silently unify them:

- grid_strategy.run_grid_backtest and grid_paper.run_grid_paper_session model
  resting limit orders and fill INTRABAR: a slot buys when candle.low touches
  its level and sells when candle.high touches the level above, even if the
  close never confirms the move (the optimistic paper model).
- demo_grid.advance_demo_grid is CLOSE-CONFIRMED: it only acts when a candle
  CLOSES at/beyond a level, and it skips still-forming (confirmed=False)
  candles entirely, because it places real (demo) market orders.

If any test here starts failing after a refactor, the paper/live gap metrics
change meaning -- treat that as a semantic change, not a bug fix.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.demo_execution import DemoOrderRecord
from okx_quant_lab.demo_grid import (
    DemoGridConfig,
    advance_demo_grid,
    new_demo_grid_state,
    open_slot_count,
)
from okx_quant_lab.grid_paper import (
    GridPaperConfig,
    new_grid_paper_state,
    run_grid_paper_session,
)
from okx_quant_lab.grid_strategy import GridBacktestConfig, run_grid_backtest
from okx_quant_lab.okx_public import Candle, InstrumentSpec


BASE_TS = 1_699_920_000_000  # midnight UTC, keeps hourly candles in one UTC day
HOUR_MS = 3_600_000

# All three engines share the same geometry: reference 100, range 10%, 4 slots
# -> levels [90, 95, 100, 105, 110]. Slot 1 buys at 95 and sells at 100.
BACKTEST_CONFIG = GridBacktestConfig(
    lower_price=90.0, upper_price=110.0, grid_count=4, initial_cash=100.0
)
PAPER_CONFIG = GridPaperConfig(
    inst_id="SOL-USDT", range_pct=10.0, grid_count=4, initial_cash=100.0
)
# max_daily_loss_pct is deliberately huge so the circuit breaker can never
# interfere with the trigger semantics under test.
DEMO_CONFIG = DemoGridConfig(
    inst_id="SOL-USDT",
    range_pct=10.0,
    grid_count=4,
    allocation_usdt=100.0,
    max_daily_loss_pct=90.0,
)
SPEC = InstrumentSpec(inst_id="SOL-USDT", lot_size=0.000001, min_size=0.001)

BUY_LEVEL = 95.0  # levels[1], slot 1's buy level
SELL_LEVEL = 100.0  # levels[2], slot 1's sell level


def _candle(
    index: int,
    open_: float,
    high: float,
    low: float,
    close: float,
    confirmed: bool = True,
) -> Candle:
    return Candle(
        timestamp_ms=BASE_TS + index * HOUR_MS,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume_base=1.0,
        volume_quote=close,
        confirmed=confirmed,
    )


class FakeExecutor:
    """Records every order request; fills market orders at reference price.

    No network, no ledger, no safety gates: this isolates advance_demo_grid's
    trigger semantics from the real DemoOrderExecutor plumbing. fee_currency
    is left empty so no fee netting kicks in.
    """

    def __init__(self) -> None:
        self.requests: list = []

    def submit(self, request, confirmed: bool = False) -> DemoOrderRecord:
        self.requests.append(request)
        if request.side == "BUY":
            fill_quantity = request.quote_amount_usdt / request.reference_price
        else:
            fill_quantity = request.base_quantity
        return DemoOrderRecord(
            request=request,
            status="FILLED",
            exchange_order_id=f"ord-{len(self.requests)}",
            exchange_client_order_id=request.client_order_id,
            fill_price=request.reference_price,
            fill_quantity=fill_quantity,
            fee=0.0,
            fee_currency="",
            message="",
        )


class IntrabarVersusCloseConfirmedTest(unittest.TestCase):
    """A wick through a level fills the paper engines but not demo_grid."""

    def test_buy_wick_fills_backtest_and_paper_but_not_demo(self) -> None:
        # Low wicks through the 95 buy level, but the candle closes back at 99:
        # the close does NOT confirm the touch.
        wick = _candle(0, open_=100.0, high=100.0, low=94.5, close=99.0)
        self.assertLessEqual(wick.low, BUY_LEVEL)  # sanity: level was touched
        self.assertGreater(wick.close, BUY_LEVEL)  # sanity: close unconfirmed

        # Backtest fills intrabar, at the level price (resting limit model).
        result = run_grid_backtest([wick], BACKTEST_CONFIG)
        self.assertEqual(len(result.fills), 1)
        self.assertEqual(result.fills[0].side, "BUY")
        self.assertEqual(result.fills[0].level_index, 1)
        self.assertEqual(result.fills[0].price, BUY_LEVEL)
        self.assertEqual(result.open_slots, 1)

        # Paper session fills intrabar too, also at the level price.
        paper_state = run_grid_paper_session(
            [wick], new_grid_paper_state(PAPER_CONFIG, 100.0), PAPER_CONFIG
        )
        self.assertEqual(len(paper_state.fills), 1)
        self.assertEqual(paper_state.fills[0].side, "BUY")
        self.assertEqual(paper_state.fills[0].price, BUY_LEVEL)
        self.assertGreater(paper_state.holdings[1], 0.0)

        # demo_grid is close-confirmed: close 99 > 95, so NO order goes out.
        executor = FakeExecutor()
        demo_state, events = advance_demo_grid(
            [wick], new_demo_grid_state(DEMO_CONFIG, 100.0), DEMO_CONFIG,
            executor, SPEC, confirmed=True,
        )
        self.assertEqual(executor.requests, [])
        self.assertEqual(events, [])
        self.assertEqual(open_slot_count(demo_state), 0)
        # The candle WAS processed (cursor advanced) -- it just didn't trigger.
        self.assertEqual(demo_state.last_timestamp_ms, wick.timestamp_ms)

    def test_sell_wick_fills_backtest_and_paper_but_not_demo(self) -> None:
        # Candle 0 closes at 94: slot 1 buys in ALL three engines (low touch
        # for backtest/paper, close-confirmed for demo). Candle 1's high wicks
        # through the 100 sell level but closes at 97 -- unconfirmed.
        entry = _candle(0, open_=100.0, high=100.0, low=94.0, close=94.0)
        wick = _candle(1, open_=94.0, high=100.5, low=94.0, close=97.0)
        self.assertGreaterEqual(wick.high, SELL_LEVEL)  # sanity: touched
        self.assertLess(wick.close, SELL_LEVEL)  # sanity: close unconfirmed

        # Backtest: full round trip on the wick, sell at the level price.
        result = run_grid_backtest([entry, wick], BACKTEST_CONFIG)
        self.assertEqual([fill.side for fill in result.fills], ["BUY", "SELL"])
        self.assertEqual(result.fills[1].price, SELL_LEVEL)
        self.assertEqual(result.round_trips, 1)
        self.assertEqual(result.open_slots, 0)

        # Paper: same round trip.
        paper_state = run_grid_paper_session(
            [entry, wick], new_grid_paper_state(PAPER_CONFIG, 100.0), PAPER_CONFIG
        )
        self.assertEqual([fill.side for fill in paper_state.fills], ["BUY", "SELL"])
        self.assertEqual(paper_state.fills[1].price, SELL_LEVEL)
        self.assertEqual(paper_state.holdings[1], 0.0)

        # demo_grid: only the BUY went out (close 94 <= 95). The wick to 100.5
        # does NOT sell, because close 97 < 100 -- position stays open.
        executor = FakeExecutor()
        demo_state, _ = advance_demo_grid(
            [entry, wick], new_demo_grid_state(DEMO_CONFIG, 100.0), DEMO_CONFIG,
            executor, SPEC, confirmed=True,
        )
        self.assertEqual([request.side for request in executor.requests], ["BUY"])
        self.assertEqual(open_slot_count(demo_state), 1)
        self.assertGreater(demo_state.holdings[1], 0.0)

    def test_demo_close_confirmation_does_fill_both_sides(self) -> None:
        # Control for the two tests above: prove the fake executor and demo
        # trigger path DO fill when the close confirms, so the non-fills above
        # are the semantics under test, not a broken fake.
        entry = _candle(0, open_=100.0, high=100.0, low=94.0, close=94.0)
        exit_ = _candle(1, open_=94.0, high=101.0, low=94.0, close=101.0)

        executor = FakeExecutor()
        demo_state, events = advance_demo_grid(
            [entry, exit_], new_demo_grid_state(DEMO_CONFIG, 100.0), DEMO_CONFIG,
            executor, SPEC, confirmed=True,
        )

        self.assertEqual(
            [request.side for request in executor.requests], ["BUY", "SELL"]
        )
        self.assertEqual(open_slot_count(demo_state), 0)
        self.assertGreater(demo_state.realized_profit, 0.0)
        self.assertTrue(any("FILLED" in event for event in events))


class UnconfirmedCandleTest(unittest.TestCase):
    """demo_grid ignores still-forming candles; the paper engines do not."""

    def test_demo_skips_unconfirmed_candle_entirely(self) -> None:
        # Close 94 would confirm a buy -- but confirmed=False means the bar is
        # still forming, and demo_grid must never let it place a live order.
        forming = _candle(0, open_=100.0, high=100.0, low=94.0, close=94.0,
                          confirmed=False)

        executor = FakeExecutor()
        demo_state, events = advance_demo_grid(
            [forming], new_demo_grid_state(DEMO_CONFIG, 100.0), DEMO_CONFIG,
            executor, SPEC, confirmed=True,
        )

        self.assertEqual(executor.requests, [])
        self.assertEqual(events, [])
        self.assertEqual(open_slot_count(demo_state), 0)
        # Skipped means SKIPPED: the cursor does not advance either, so the
        # same bar is re-processed once it closes (contrast with the processed
        # no-trigger candle in the intrabar test, where the cursor advances).
        self.assertEqual(demo_state.last_timestamp_ms, 0)

    def test_paper_and_backtest_fill_on_unconfirmed_candles(self) -> None:
        # CURRENT BEHAVIOR, locked deliberately: run_grid_paper_session and
        # run_grid_backtest never look at candle.confirmed -- they fill on a
        # still-forming bar exactly as on a closed one. In production they are
        # fed already-confirmed candles by their callers, but the functions
        # themselves are confirmed-agnostic. If a refactor adds a confirmed
        # gate here, the paper track's semantics (and its optimism vs demo)
        # change -- this test forces that to be a conscious decision.
        forming = _candle(0, open_=100.0, high=100.0, low=94.0, close=94.0,
                          confirmed=False)

        paper_state = run_grid_paper_session(
            [forming], new_grid_paper_state(PAPER_CONFIG, 100.0), PAPER_CONFIG
        )
        self.assertEqual(len(paper_state.fills), 1)
        self.assertEqual(paper_state.fills[0].side, "BUY")
        self.assertGreater(paper_state.holdings[1], 0.0)
        # And unlike demo_grid, the cursor advances past the forming bar.
        self.assertEqual(paper_state.last_timestamp_ms, forming.timestamp_ms)

        result = run_grid_backtest([forming], BACKTEST_CONFIG)
        self.assertEqual(len(result.fills), 1)
        self.assertEqual(result.fills[0].side, "BUY")


if __name__ == "__main__":
    unittest.main()
