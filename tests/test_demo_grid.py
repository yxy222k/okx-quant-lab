from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.demo_execution import DemoExecutionLimits, DemoOrderExecutor
from okx_quant_lab.demo_grid import (
    DemoGridConfig,
    advance_demo_grid,
    demo_grid_equity,
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
