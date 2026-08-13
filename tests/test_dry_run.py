from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.dry_run import (
    DryRunLimits,
    DryRunOrderManager,
    OrderRequest,
    build_sma_order_request,
    load_order_ledger,
    save_order_ledger,
    sma_signal,
)
from okx_quant_lab.okx_public import Candle
from okx_quant_lab.paper import PaperConfig, PaperState


class DryRunTest(unittest.TestCase):
    def test_blocks_order_above_notional_cap(self) -> None:
        manager = DryRunOrderManager()
        order = manager.submit(
            _request("BUY", quote_amount_usdt=50, base_quantity=0),
            DryRunLimits(max_order_usdt=25),
        )

        self.assertEqual(order.status, "BLOCKED")
        self.assertIn("exceeds cap", order.message)

    def test_duplicate_client_order_id_is_not_recorded_twice(self) -> None:
        manager = DryRunOrderManager()
        request = _request("BUY", quote_amount_usdt=10, base_quantity=0)

        first = manager.submit(request, DryRunLimits(max_order_usdt=25))
        second = manager.submit(request, DryRunLimits(max_order_usdt=25))

        self.assertEqual(first.status, "DRY_FILLED")
        self.assertEqual(second.status, "DUPLICATE")
        self.assertEqual(len(manager.orders), 1)

    def test_ledger_round_trip(self) -> None:
        manager = DryRunOrderManager()
        manager.submit(_request("BUY", quote_amount_usdt=10, base_quantity=0), DryRunLimits())

        with tempfile.TemporaryDirectory(dir=ROOT) as dirname:
            path = Path(dirname) / "orders.json"
            save_order_ledger(path, manager.orders)
            loaded = load_order_ledger(path)

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].request.client_order_id, "test-order")

    def test_build_sma_order_request_returns_buy_when_signal_long_and_flat(self) -> None:
        candles = _candles([100 + index for index in range(60)])
        config = PaperConfig(inst_id="TEST-USDT", fast_window=5, slow_window=10)
        state = PaperState(cash=1000, asset=0, last_timestamp_ms=candles[-1].timestamp_ms, fills=[])

        request = build_sma_order_request(candles, state, config)

        self.assertEqual(sma_signal(candles, config), "LONG")
        self.assertIsNotNone(request)
        self.assertEqual(request.side, "BUY")


def _request(side: str, quote_amount_usdt: float, base_quantity: float) -> OrderRequest:
    return OrderRequest(
        client_order_id="test-order",
        inst_id="TEST-USDT",
        side=side,
        quote_amount_usdt=quote_amount_usdt,
        base_quantity=base_quantity,
        reference_price=10.0,
        created_at_ms=1_700_000_000_000,
        reason="unit test",
    )


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
