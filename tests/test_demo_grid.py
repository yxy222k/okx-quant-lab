from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.demo_execution import DemoExecutionLimits, DemoOrderExecutor, DemoOrderRecord
from okx_quant_lab.dry_run import OrderRequest
from okx_quant_lab.demo_grid import (
    DemoGridConfig,
    advance_demo_grid,
    apply_late_fill,
    demo_grid_equity,
    in_outage,
    load_demo_grid_state,
    new_demo_grid_state,
    open_slot_count,
    save_demo_grid_state,
)
from okx_quant_lab.okx_demo_private import DemoCredentials
from okx_quant_lab.okx_public import Candle, InstrumentSpec


CREDENTIALS = DemoCredentials(api_key="k", secret_key="s", passphrase="p")
SPEC = InstrumentSpec(inst_id="SOL-USDT", lot_size=0.000001, min_size=0.001)
# range 10% around 100 with 4 slots: levels [90, 95, 100, 105, 110]
CONFIG = DemoGridConfig(
    inst_id="SOL-USDT",
    range_pct=10.0,
    grid_count=4,
    allocation_usdt=100.0,
    max_daily_loss_pct=3.0,
)


def _fill_at_close(calls: list) -> callable:
    """Fake exchange: market orders fill exactly at the request's close price."""
    pending: dict = {}

    def fake_request(credentials, method, path, body=None):
        calls.append((method, path, body))
        if method == "POST":
            pending["body"] = body
            return {"code": "0", "data": [{"sCode": "0", "ordId": f"ord-{len(calls)}"}]}
        body = pending["body"]
        price = float(body["_close"])
        if body["side"] == "buy":
            quantity = float(body["sz"]) * 0.999 / price
            fee, fee_ccy = -quantity * 0.001, "SOL"
            fill_quantity = quantity + quantity * 0.001  # accFillSz before fee
        else:
            fill_quantity = float(body["sz"])
            fee, fee_ccy = -fill_quantity * price * 0.001, "USDT"
        return {
            "code": "0",
            "data": [
                {
                    "state": "filled",
                    "avgPx": str(price),
                    "accFillSz": str(fill_quantity),
                    "fee": str(fee),
                    "feeCcy": fee_ccy,
                }
            ],
        }

    return fake_request


class _CloseAwareExecutor(DemoOrderExecutor):
    """Injects the request's reference close price into the fake exchange body."""

    def submit(self, request, confirmed=False):
        self._close = request.reference_price
        return super().submit(request, confirmed=confirmed)

    def _place_and_confirm(self, request):
        original = self._request_fn

        def wrapped(credentials, method, path, body=None):
            if body is not None:
                body = dict(body, _close=str(self._close))
            return original(credentials, method, path, body)

        self._request_fn = wrapped
        try:
            return super()._place_and_confirm(request)
        finally:
            self._request_fn = original


def _executor(calls: list) -> DemoOrderExecutor:
    # Cap must sit above slot notional at SELL time (position sold above its
    # buy level), so it is deliberately higher than slot_cash (25).
    return _CloseAwareExecutor(
        CREDENTIALS, DemoExecutionLimits(max_order_usdt=50.0), request_fn=_fill_at_close(calls)
    )


def _candles(closes: list[float], start_index: int = 0) -> list[Candle]:
    candles = []
    previous = closes[0]
    for offset, close in enumerate(closes):
        candles.append(
            Candle(
                # Base is exactly midnight UTC so hourly candles stay inside
                # one UTC day and start_index=24 lands on the next day.
                timestamp_ms=1_699_920_000_000 + (start_index + offset) * 3_600_000,
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


class DemoGridTest(unittest.TestCase):
    def test_unconfirmed_candle_never_places_an_order(self) -> None:
        calls: list = []
        state = new_demo_grid_state(CONFIG, reference_price=100.0)

        # A still-forming candle that closes below a buy level must be skipped.
        unconfirmed = _candles([100, 94])
        unconfirmed[-1] = Candle(
            timestamp_ms=unconfirmed[-1].timestamp_ms,
            open=unconfirmed[-1].open,
            high=unconfirmed[-1].high,
            low=unconfirmed[-1].low,
            close=unconfirmed[-1].close,
            volume_base=1.0,
            volume_quote=94.0,
            confirmed=False,
        )

        state, events = advance_demo_grid(
            unconfirmed, state, CONFIG, _executor(calls), SPEC, confirmed=True
        )

        self.assertEqual([c for c in calls if c[0] == "POST"], [])
        self.assertEqual(open_slot_count(state), 0)

    def test_legacy_state_without_deploy_timestamp_loads(self) -> None:
        import json
        from dataclasses import asdict

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.json"
            data = asdict(new_demo_grid_state(CONFIG, reference_price=100.0))
            del data["deploy_timestamp_ms"]  # simulate a pre-field state file
            path.write_text(json.dumps(data), encoding="utf-8")

            loaded = load_demo_grid_state(path)

        self.assertEqual(loaded.deploy_timestamp_ms, 0)

    def test_deploy_timestamp_survives_save_load_and_advance(self) -> None:
        from dataclasses import replace

        config = CONFIG
        state = replace(new_demo_grid_state(config, 100.0), deploy_timestamp_ms=12345)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.json"
            save_demo_grid_state(path, state)
            self.assertEqual(load_demo_grid_state(path).deploy_timestamp_ms, 12345)

        advanced, _ = advance_demo_grid(
            _candles([100, 94]), state, config, _executor([]), SPEC, confirmed=True
        )
        self.assertEqual(advanced.deploy_timestamp_ms, 12345)

    def test_outages_survive_save_load_and_advance(self) -> None:
        # The deployed code must carry this field through every save, or one
        # cron cycle would silently erase the record reconciliation relies on.
        import json
        from dataclasses import asdict, replace

        config = CONFIG
        state = replace(new_demo_grid_state(config, 100.0), outages=[[100, 200]])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.json"
            save_demo_grid_state(path, state)
            self.assertEqual(load_demo_grid_state(path).outages, [[100, 200]])

            legacy = asdict(new_demo_grid_state(config, 100.0))
            del legacy["outages"]
            path.write_text(json.dumps(legacy), encoding="utf-8")
            self.assertEqual(load_demo_grid_state(path).outages, [])

        advanced, _ = advance_demo_grid(
            _candles([100, 94]), state, config, _executor([]), SPEC, confirmed=True
        )
        self.assertEqual(advanced.outages, [[100, 200]])
        self.assertTrue(in_outage(advanced, 150))
        self.assertFalse(in_outage(advanced, 201))

    def test_buys_on_close_below_level_and_sells_above(self) -> None:
        calls: list = []
        state = new_demo_grid_state(CONFIG, reference_price=100.0)

        # close 94 <= level 95 -> buy slot 1; close 101 >= level 100 -> sell it.
        state, events = advance_demo_grid(
            _candles([100, 94, 101]), state, CONFIG, _executor(calls), SPEC, confirmed=True
        )

        self.assertEqual(open_slot_count(state), 0)
        self.assertGreater(state.realized_profit, 0)
        posts = [c for c in calls if c[0] == "POST"]
        self.assertEqual(len(posts), 2)
        self.assertTrue(any("BUY" in event and "FILLED" in event for event in events))
        self.assertTrue(any("SELL" in event and "FILLED" in event for event in events))

    def test_unconfirmed_orders_never_reach_exchange(self) -> None:
        calls: list = []
        state = new_demo_grid_state(CONFIG, reference_price=100.0)

        state, events = advance_demo_grid(
            _candles([100, 94]), state, CONFIG, _executor(calls), SPEC, confirmed=False
        )

        self.assertEqual([c for c in calls if c[0] == "POST"], [])
        self.assertEqual(open_slot_count(state), 0)
        self.assertTrue(any("BLOCKED" in event for event in events))

    def test_resume_skips_processed_candles(self) -> None:
        calls: list = []
        executor = _executor(calls)
        state = new_demo_grid_state(CONFIG, reference_price=100.0)
        candles = _candles([100, 94, 101])

        state, _ = advance_demo_grid(candles, state, CONFIG, executor, SPEC, confirmed=True)
        posts_after_first = len([c for c in calls if c[0] == "POST"])

        state, events = advance_demo_grid(candles, state, CONFIG, executor, SPEC, confirmed=True)

        self.assertEqual(len([c for c in calls if c[0] == "POST"]), posts_after_first)
        self.assertEqual(events, [])

    def test_circuit_breaker_stops_orders_for_the_day(self) -> None:
        calls: list = []
        state = new_demo_grid_state(CONFIG, reference_price=100.0)

        # Same UTC day: buy at 94, then price collapses; equity drops beyond 3%.
        state, events = advance_demo_grid(
            _candles([100, 94, 80, 75]), state, CONFIG, _executor(calls), SPEC, confirmed=True
        )

        self.assertTrue(state.breaker_tripped)
        self.assertTrue(any("CIRCUIT BREAKER" in event for event in events))
        # Only the first buy went out; the drops to 80/75 triggered no new buys.
        self.assertEqual(len([c for c in calls if c[0] == "POST"]), 1)

    def test_breaker_resets_on_new_utc_day(self) -> None:
        calls: list = []
        state = new_demo_grid_state(CONFIG, reference_price=100.0)
        state, _ = advance_demo_grid(
            _candles([100, 94, 80, 75]), state, CONFIG, _executor(calls), SPEC, confirmed=True
        )
        self.assertTrue(state.breaker_tripped)

        next_day = _candles([75], start_index=24)
        state, _ = advance_demo_grid(next_day, state, CONFIG, _executor(calls), SPEC, confirmed=True)

        self.assertFalse(state.breaker_tripped)

    def test_state_roundtrip(self) -> None:
        calls: list = []
        state = new_demo_grid_state(CONFIG, reference_price=100.0)
        state, _ = advance_demo_grid(
            _candles([100, 94]), state, CONFIG, _executor(calls), SPEC, confirmed=True
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo_grid.json"
            save_demo_grid_state(path, state)
            loaded = load_demo_grid_state(path)

        self.assertEqual(state, loaded)
        self.assertAlmostEqual(
            demo_grid_equity(loaded, 94.0), demo_grid_equity(state, 94.0)
        )


if __name__ == "__main__":
    unittest.main()


def _late_record(side: str, slot: int, status: str = "FILLED") -> DemoOrderRecord:
    return DemoOrderRecord(
        request=OrderRequest(
            client_order_id=f"demogrid:SOL-USDT:1699920000000:{side}:L{slot}",
            inst_id="SOL-USDT", side=side,
            quote_amount_usdt=25.0 if side == "BUY" else 0.0,
            base_quantity=0.26 if side == "SELL" else 0.0,
            reference_price=94.0, created_at_ms=1_699_920_000_000, reason="test",
        ),
        status=status, exchange_order_id="ord", exchange_client_order_id="cl",
        fill_price=94.0 if side == "BUY" else 101.0,
        fill_quantity=0.266 if side == "BUY" else 0.26,
        fee=-0.000266 if side == "BUY" else -0.02626,
        fee_currency="SOL" if side == "BUY" else "USDT",
        message="",
    )


class ApplyLateFillTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = new_demo_grid_state(CONFIG, reference_price=100.0)

    def test_late_buy_books_like_an_immediate_fill(self) -> None:
        state, event = apply_late_fill(self.state, CONFIG, _late_record("BUY", 1))

        self.assertAlmostEqual(state.cash, 100.0 - CONFIG.slot_cash)
        self.assertAlmostEqual(state.holdings[1], 0.266 - 0.000266)
        self.assertFalse(state.armed[1])
        self.assertIn("booked", event)

    def test_late_buy_into_an_occupied_slot_is_refused(self) -> None:
        booked, _ = apply_late_fill(self.state, CONFIG, _late_record("BUY", 1))

        again, event = apply_late_fill(booked, CONFIG, _late_record("BUY", 1))

        self.assertEqual(again, booked)  # a repeat is a no-op
        self.assertIn("NOT booked", event)

    def test_slot_override_books_into_another_slot(self) -> None:
        state, _ = apply_late_fill(self.state, CONFIG, _late_record("BUY", 1), slot=3)

        self.assertEqual(state.holdings[1], 0.0)
        self.assertGreater(state.holdings[3], 0.0)
        self.assertFalse(state.armed[3])

    def test_late_sell_realizes_against_slot_cash(self) -> None:
        bought, _ = apply_late_fill(self.state, CONFIG, _late_record("BUY", 1))

        sold, event = apply_late_fill(bought, CONFIG, _late_record("SELL", 1))

        proceeds = 0.26 * 101.0 - 0.02626
        self.assertEqual(sold.holdings[1], 0.0)
        self.assertAlmostEqual(sold.cash, bought.cash + proceeds)
        self.assertAlmostEqual(sold.realized_profit, proceeds - CONFIG.slot_cash)
        self.assertIn("booked", event)

    def test_late_sell_from_an_empty_slot_is_refused(self) -> None:
        state, event = apply_late_fill(self.state, CONFIG, _late_record("SELL", 1))

        self.assertEqual(state, self.state)
        self.assertIn("NOT booked", event)

    def test_non_filled_resolution_books_nothing(self) -> None:
        for status in ("CANCELED", "PARTIAL"):
            with self.subTest(status=status):
                state, event = apply_late_fill(
                    self.state, CONFIG, _late_record("BUY", 1, status=status)
                )
                self.assertEqual(state, self.state)
                self.assertIn(status, event)
