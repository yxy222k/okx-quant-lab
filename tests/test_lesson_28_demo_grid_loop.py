from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import lesson_28_demo_grid_loop as loop_mod

from okx_quant_lab.demo_execution import load_demo_order_ledger
from okx_quant_lab.demo_grid import DemoGridConfig, load_demo_grid_state
from okx_quant_lab.okx_demo_private import DemoCredentials
from okx_quant_lab.okx_public import Candle, InstrumentSpec


# 2023-11-14T22:13:20+00:00
TS = 1_700_000_000_000
BAR_MS = 900_000  # one 15m bar


def _candle(timestamp_ms: int, close: float, confirmed: bool = True) -> Candle:
    return Candle(
        timestamp_ms=timestamp_ms,
        open=close,
        high=close,
        low=close,
        close=close,
        volume_base=1.0,
        volume_quote=close,
        confirmed=confirmed,
    )


class MarketConfigTest(unittest.TestCase):
    def test_wires_inst_id_into_config(self) -> None:
        for inst_id in ("BTC-USDT", "ETH-USDT", "SOL-USDT"):
            config = loop_mod.market_config(inst_id)
            self.assertIsInstance(config, DemoGridConfig)
            self.assertEqual(config.inst_id, inst_id)

    def test_grid_parameters(self) -> None:
        config = loop_mod.market_config("BTC-USDT")
        self.assertEqual(config.range_pct, 15.0)
        self.assertEqual(config.grid_count, 20)
        self.assertEqual(config.allocation_usdt, 100.0)
        self.assertEqual(config.max_daily_loss_pct, 3.0)

    def test_slot_cash_is_allocation_over_grid_count(self) -> None:
        config = loop_mod.market_config("ETH-USDT")
        self.assertAlmostEqual(config.slot_cash, 5.0)


class PathWiringTest(unittest.TestCase):
    def test_state_path_layout(self) -> None:
        path = loop_mod.state_path("BTC-USDT")
        self.assertEqual(
            path,
            loop_mod.ROOT / "data" / "demo" / "BTC-USDT_15m_demo_grid_state.json",
        )

    def test_ledger_path_layout(self) -> None:
        path = loop_mod.ledger_path("ETH-USDT")
        self.assertEqual(
            path,
            loop_mod.ROOT / "data" / "orders" / "demo_grid_orders_ETH-USDT.json",
        )

    def test_candle_path_layout(self) -> None:
        path = loop_mod.candle_path("SOL-USDT")
        self.assertEqual(
            path,
            loop_mod.ROOT / "data" / "candles" / "SOL-USDT_15m_demo.csv",
        )

    def test_bar_embedded_in_time_scoped_paths(self) -> None:
        # State and candle files are per-bar artifacts; a BAR change must not
        # silently reuse files written for a different timeframe.
        self.assertIn(f"_{loop_mod.BAR}_", loop_mod.state_path("BTC-USDT").name)
        self.assertIn(f"_{loop_mod.BAR}_", loop_mod.candle_path("BTC-USDT").name)

    def test_all_market_paths_are_distinct(self) -> None:
        paths = [
            fn(inst_id)
            for inst_id in loop_mod.MARKETS
            for fn in (loop_mod.state_path, loop_mod.ledger_path, loop_mod.candle_path)
        ]
        self.assertEqual(len(paths), len(set(paths)))


class ConstantsTest(unittest.TestCase):
    def test_candle_retention(self) -> None:
        self.assertEqual(loop_mod.CANDLE_RETENTION, 12_000)

    def test_retention_covers_the_reconcile_replay_window(self) -> None:
        # 12000 15m bars ~= 125 days; the docstring promises the whole demo
        # phase stays replayable, so retention must dwarf the per-run fetch.
        days_covered = loop_mod.CANDLE_RETENTION * 15 / (60 * 24)
        self.assertGreaterEqual(days_covered, 100)
        self.assertGreaterEqual(loop_mod.CANDLE_RETENTION, 300)

    def test_markets_and_bar(self) -> None:
        self.assertEqual(loop_mod.MARKETS, ["BTC-USDT", "ETH-USDT", "SOL-USDT"])
        self.assertEqual(loop_mod.BAR, "15m")

    def test_order_limit_cap(self) -> None:
        self.assertEqual(loop_mod.LIMITS.max_order_usdt, 25.0)


class SeenAtTest(unittest.TestCase):
    def test_formats_utc_iso(self) -> None:
        self.assertEqual(loop_mod._seen_at(TS), "2023-11-14T22:13:20+00:00")

    def test_epoch_zero(self) -> None:
        self.assertEqual(loop_mod._seen_at(0), "1970-01-01T00:00:00+00:00")


class RunMarketTest(unittest.TestCase):
    """_run_market with every I/O seam patched at module level.

    Network never happens: refresh_candles / fetch_instrument_spec are fakes,
    and orders run with confirmed=False so the Lesson 12 safety gate BLOCKS
    each submission before DemoOrderExecutor reaches its request function.
    All file paths are rerouted into a TemporaryDirectory.
    """

    PATCHED = (
        "refresh_candles",
        "fetch_instrument_spec",
        "state_path",
        "ledger_path",
        "candle_path",
    )

    def setUp(self) -> None:
        tmp_holder = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_holder.cleanup)
        self.tmp = Path(tmp_holder.name)

        self._originals = {name: getattr(loop_mod, name) for name in self.PATCHED}
        self.addCleanup(self._restore)

        self.refresh_calls: list[dict] = []
        self.candles = [_candle(TS, 100.0)]

        def fake_refresh(path, inst_id, bar, target_count, retention):
            self.refresh_calls.append(
                {
                    "path": path,
                    "inst_id": inst_id,
                    "bar": bar,
                    "target_count": target_count,
                    "retention": retention,
                }
            )
            return list(self.candles)

        loop_mod.refresh_candles = fake_refresh
        loop_mod.fetch_instrument_spec = lambda inst_id: InstrumentSpec(
            inst_id=inst_id, lot_size=0.000001, min_size=0.001
        )
        loop_mod.state_path = lambda inst_id: self.tmp / f"{inst_id}_state.json"
        loop_mod.ledger_path = lambda inst_id: self.tmp / f"{inst_id}_ledger.json"
        loop_mod.candle_path = lambda inst_id: self.tmp / f"{inst_id}_candles.csv"

        self.credentials = DemoCredentials(api_key="k", secret_key="s", passphrase="p")

    def _restore(self) -> None:
        for name, value in self._originals.items():
            setattr(loop_mod, name, value)

    def _run(self, inst_id: str = "BTC-USDT", confirmed: bool = False):
        return loop_mod._run_market(inst_id, self.credentials, confirmed)

    def test_refresh_candles_wiring(self) -> None:
        self._run("BTC-USDT")
        self.assertEqual(len(self.refresh_calls), 1)
        call = self.refresh_calls[0]
        self.assertEqual(call["path"], self.tmp / "BTC-USDT_candles.csv")
        self.assertEqual(call["inst_id"], "BTC-USDT")
        self.assertEqual(call["bar"], loop_mod.BAR)
        self.assertEqual(call["target_count"], 300)
        self.assertEqual(call["retention"], loop_mod.CANDLE_RETENTION)

    def test_first_run_deploys_and_flags_attention(self) -> None:
        lines, attention = self._run("BTC-USDT")

        self.assertTrue(attention)
        self.assertEqual(len(lines), 2)
        self.assertEqual(
            lines[0],
            "BTC-USDT: deployed grid 85.0000..115.0000 "
            "(20 slots x 5.00 USDT, 15m bars)",
        )
        self.assertEqual(
            lines[1],
            "BTC-USDT: equity=100.00/100.00 open=0/20 realized=0.00 "
            "mark=100.0000 breaker=ok @ 2023-11-14T22:13:20+00:00",
        )

    def test_deploy_anchors_state_at_current_candle(self) -> None:
        # Historical candles must never replay as live orders: a fresh grid
        # starts from the CURRENT candle with both timestamps pinned to it.
        self._run("BTC-USDT")

        state = load_demo_grid_state(self.tmp / "BTC-USDT_state.json")
        self.assertEqual(state.last_timestamp_ms, TS)
        self.assertEqual(state.deploy_timestamp_ms, TS)
        self.assertEqual(state.cash, 100.0)
        self.assertEqual(state.realized_profit, 0.0)
        self.assertFalse(state.breaker_tripped)
        self.assertEqual(len(state.levels), 21)
        self.assertAlmostEqual(state.levels[0], 85.0)
        self.assertAlmostEqual(state.levels[-1], 115.0)
        self.assertEqual(state.holdings, [0.0] * 20)

        # Ledger written even when empty, so the audit file always exists.
        self.assertEqual(load_demo_order_ledger(self.tmp / "BTC-USDT_ledger.json"), [])

    def test_second_run_is_quiet_and_reuses_state(self) -> None:
        self._run("BTC-USDT")
        lines, attention = self._run("BTC-USDT")

        self.assertFalse(attention)
        self.assertEqual(
            lines,
            [
                "BTC-USDT: equity=100.00/100.00 open=0/20 realized=0.00 "
                "mark=100.0000 breaker=ok"
            ],
        )
        # No re-deploy: the frozen deploy anchor survives the second run.
        state = load_demo_grid_state(self.tmp / "BTC-USDT_state.json")
        self.assertEqual(state.deploy_timestamp_ms, TS)

    def test_unconfirmed_orders_blocked_and_below_range_warns(self) -> None:
        self._run("BTC-USDT")

        # New candle closes below the whole grid: the 10 armed buy levels all
        # trigger, but confirmed=False means every one is BLOCKED pre-network.
        self.candles = [_candle(TS, 100.0), _candle(TS + BAR_MS, 80.0)]
        lines, attention = self._run("BTC-USDT", confirmed=False)

        self.assertTrue(attention)
        blocked = [line for line in lines if "-> BLOCKED" in line]
        self.assertEqual(len(blocked), 10)
        for line in blocked:
            self.assertTrue(line.startswith("BTC-USDT: BUY BTC-USDT @level "))
            self.assertIn("safety gate failed", line)

        self.assertEqual(
            lines[-2],
            "BTC-USDT: equity=100.00/100.00 open=0/20 realized=0.00 "
            "mark=80.0000 breaker=ok @ 2023-11-14T22:28:20+00:00",
        )
        self.assertEqual(
            lines[-1],
            "BTC-USDT: WARNING mark 80.0000 below grid range 85.0000",
        )

        # Blocked orders change nothing: no cash spent, no slots opened.
        state = load_demo_grid_state(self.tmp / "BTC-USDT_state.json")
        self.assertEqual(state.cash, 100.0)
        self.assertEqual(state.holdings, [0.0] * 20)
        self.assertEqual(state.last_timestamp_ms, TS + BAR_MS)

        # Every blocked attempt still lands in the audit ledger.
        records = load_demo_order_ledger(self.tmp / "BTC-USDT_ledger.json")
        self.assertEqual(len(records), 10)
        self.assertTrue(all(record.status == "BLOCKED" for record in records))


if __name__ == "__main__":
    unittest.main()
