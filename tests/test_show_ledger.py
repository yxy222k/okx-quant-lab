from __future__ import annotations

import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from okx_quant_lab.demo_execution import (
    DemoOrderRecord,
    load_demo_order_ledger,
    save_demo_order_ledger,
)
from okx_quant_lab.demo_grid import (
    DemoGridConfig,
    new_demo_grid_state,
    save_demo_grid_state,
)
from okx_quant_lab.dry_run import OrderRequest


# 2023-11-14 22:13:20 UTC
TS_MS = 1_700_000_000_000


def _request(side: str = "BUY", reason: str = "unit-test buy") -> OrderRequest:
    return OrderRequest(
        client_order_id=f"test:{side}:1",
        inst_id="SOL-USDT",
        side=side,
        quote_amount_usdt=10.0 if side == "BUY" else 0.0,
        base_quantity=0.05 if side == "SELL" else 0.0,
        reference_price=100.0,
        created_at_ms=TS_MS,
        reason=reason,
    )


def _filled_record() -> DemoOrderRecord:
    return DemoOrderRecord(
        request=_request("BUY", reason="grid buy level 3"),
        status="FILLED",
        exchange_order_id="ord-1",
        exchange_client_order_id="a" * 32,
        fill_price=101.5,
        fill_quantity=0.0985,
        fee=0.0001,
        fee_currency="SOL",
        message="",
    )


def _blocked_record() -> DemoOrderRecord:
    return DemoOrderRecord(
        request=_request("SELL", reason="over the notional cap"),
        status="BLOCKED",
        exchange_order_id="",
        exchange_client_order_id="",
        fill_price=0.0,
        fill_quantity=0.0,
        fee=0.0,
        fee_currency="",
        message="blocked by safety gate",
    )


class SeenAtTest(unittest.TestCase):
    def test_zero_timestamp_reads_never(self) -> None:
        import show_ledger

        self.assertEqual(show_ledger._seen_at(0).strip(), "never")

    def test_known_timestamp_formats_as_utc_minute(self) -> None:
        import show_ledger

        self.assertEqual(show_ledger._seen_at(TS_MS), "2023-11-14 22:13 UTC")


class MainOutputTest(unittest.TestCase):
    def _run_main(self, ledgers: dict, grid_paths: list) -> str:
        import show_ledger

        buffer = io.StringIO()
        with mock.patch.object(show_ledger, "LEDGERS", ledgers), \
                mock.patch.object(show_ledger, "GRID_STATE_PATHS", grid_paths), \
                contextlib.redirect_stdout(buffer):
            exit_code = show_ledger.main()
        self.assertEqual(exit_code, 0)
        return buffer.getvalue()

    def test_ledger_records_summary_and_fees(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "demo_orders.json"
            save_demo_order_ledger(ledger_path, [_filled_record(), _blocked_record()])
            # Sanity: the fixture round-trips through the real save/load pair.
            self.assertEqual(len(load_demo_order_ledger(ledger_path)), 2)

            output = self._run_main({"unit ledger": ledger_path}, [])

        self.assertIn("=== unit ledger: demo_orders.json ===", output)
        # Filled row: timestamp, side, instrument, status, fill details.
        self.assertIn("2023-11-14 22:13 UTC", output)
        self.assertIn("BUY", output)
        self.assertIn("SOL-USDT", output)
        self.assertIn("FILLED", output)
        self.assertIn("fill=101.5000", output)
        self.assertIn("qty=0.098500", output)
        self.assertIn("fee=0.000100 SOL", output)
        # Blocked row shows the message instead of fill details.
        self.assertIn("BLOCKED", output)
        self.assertIn("blocked by safety gate", output)
        self.assertNotIn("fill=0.0000", output)
        # Reasons are echoed for every record.
        self.assertIn("reason: grid buy level 3", output)
        self.assertIn("reason: over the notional cap", output)
        # Status counts are sorted, and only non-zero fees are totalled.
        self.assertIn("-- 2 records: BLOCKED=1, FILLED=1", output)
        self.assertIn("-- total fees: 0.000100 SOL", output)

    def test_missing_ledger_prints_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does_not_exist.json"
            output = self._run_main({"empty ledger": missing}, [])

        self.assertIn("=== empty ledger: does_not_exist.json ===", output)
        self.assertIn("(no ledger yet)", output)
        # The missing-ledger branch must not attempt a summary line.
        self.assertNotIn("records:", output)

    def test_grid_state_section(self) -> None:
        config = DemoGridConfig(
            inst_id="SOL-USDT",
            range_pct=15.0,
            grid_count=10,
            allocation_usdt=100.0,
        )
        state = new_demo_grid_state(config, reference_price=100.0)

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "SOL-USDT_demo_grid_state.json"
            save_demo_grid_state(state_path, state)
            output = self._run_main({}, [state_path])

        self.assertIn("=== grid state: SOL-USDT_demo_grid_state.json ===", output)
        # 100 +/- 15% with 10 slots -> levels span 85..115.
        self.assertIn("range:    85.0000 .. 115.0000", output)
        self.assertIn("cash:     100.00 USDT   realized: 0.00 USDT", output)
        self.assertIn("holdings: (all slots empty)", output)
        self.assertIn("breaker:  ok (day n/a, day-start equity 100.00)", output)
        self.assertIn("last processed: never", output)

    def test_grid_state_with_holdings_and_tripped_breaker(self) -> None:
        from dataclasses import replace

        config = DemoGridConfig(grid_count=4, allocation_usdt=40.0)
        fresh = new_demo_grid_state(config, reference_price=100.0)
        state = replace(
            fresh,
            holdings=[0.0, 0.25, 0.0, 0.0],
            breaker_tripped=True,
            day_utc="2023-11-14",
            last_timestamp_ms=TS_MS,
        )

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "grid_state.json"
            save_demo_grid_state(state_path, state)
            output = self._run_main({}, [state_path])

        self.assertIn("holdings: {1: 0.25}", output)
        self.assertIn("breaker:  TRIPPED (day 2023-11-14", output)
        self.assertIn("last processed: 2023-11-14 22:13 UTC", output)


if __name__ == "__main__":
    unittest.main()
