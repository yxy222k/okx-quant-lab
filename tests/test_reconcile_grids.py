from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.demo_grid import DemoGridConfig, new_demo_grid_state
from okx_quant_lab.okx_public import Candle
from okx_quant_lab.reconcile import replay_window as _replay_window


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



class ReconcileMarketTest(unittest.TestCase):
    """reconcile_market end to end on a temp project root."""

    INST = "SOL-USDT"

    def _write(self, root: Path, state, candles, records) -> None:
        from okx_quant_lab.candle_store import save_candles_csv
        from okx_quant_lab.demo_execution import save_demo_order_ledger
        from okx_quant_lab.demo_grid import save_demo_grid_state

        save_demo_grid_state(root / "data" / "demo" / f"{self.INST}_15m_demo_grid_state.json", state)
        save_candles_csv(root / "data" / "candles" / f"{self.INST}_15m_demo.csv", candles)
        save_demo_order_ledger(root / "data" / "orders" / f"demo_grid_orders_{self.INST}.json", records)

    def _record(self, created_at_ms: int, side: str = "BUY"):
        from okx_quant_lab.demo_execution import DemoOrderRecord
        from okx_quant_lab.dry_run import OrderRequest

        return DemoOrderRecord(
            request=OrderRequest(
                client_order_id=f"demogrid:{self.INST}:{created_at_ms}:{side}:L1",
                inst_id=self.INST, side=side, quote_amount_usdt=5.0, base_quantity=0.0,
                reference_price=100.0, created_at_ms=created_at_ms, reason="test",
            ),
            status="FILLED", exchange_order_id="o", exchange_client_order_id="c",
            fill_price=100.0, fill_quantity=0.05, fee=0.0, fee_currency="USDT", message="",
        )

    def _swinging(self, n: int):
        # Wicks down to 94 and up to 106 every other bar: the intrabar paper
        # model fills on most of them.
        start = 1_700_000_000_000
        return [
            Candle(timestamp_ms=start + i * 900_000, open=100.0,
                   high=106.0 if i % 2 else 101.0, low=99.0 if i % 2 else 94.0,
                   close=100.0, volume_base=1.0, volume_quote=100.0, confirmed=True)
            for i in range(n)
        ]

    def test_counts_only_this_deployments_fills(self) -> None:
        import tempfile
        from okx_quant_lab.reconcile import reconcile_market

        candles = self._swinging(20)
        deploy_ts = candles[0].timestamp_ms
        records = [
            self._record(deploy_ts - 10 * 900_000),          # earlier phase
            self._record(deploy_ts - 9 * 900_000, "SELL"),   # earlier phase
            self._record(candles[3].timestamp_ms),
            self._record(candles[6].timestamp_ms, "SELL"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            self._write(Path(tmp), _state(deploy_ts), candles, records)
            row = reconcile_market(self.INST, Path(tmp))

        self.assertEqual((row["demo_buy"], row["demo_sell"]), (1, 1))

    def test_outage_span_is_not_traded_by_the_paper_replay(self) -> None:
        import tempfile
        from okx_quant_lab.reconcile import reconcile_market

        candles = self._swinging(40)
        deploy_ts = candles[0].timestamp_ms
        outage = [candles[5].timestamp_ms, candles[34].timestamp_ms]
        rows = {}
        for label, spans in (("plain", []), ("outage", [outage])):
            with tempfile.TemporaryDirectory() as tmp:
                state = replace(_state(deploy_ts), outages=spans)
                self._write(Path(tmp), state, candles, [self._record(candles[2].timestamp_ms)])
                rows[label] = reconcile_market(self.INST, Path(tmp))

        plain = rows["plain"]["paper_buy"] + rows["plain"]["paper_sell"]
        gated = rows["outage"]["paper_buy"] + rows["outage"]["paper_sell"]
        self.assertGreater(plain, gated)
        self.assertEqual(rows["plain"]["outage_days"], 0.0)
        self.assertAlmostEqual(rows["outage"]["outage_days"], 29 * 900_000 / 86_400_000)


if __name__ == "__main__":
    unittest.main()
