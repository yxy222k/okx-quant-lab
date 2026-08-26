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


class _PatchMixin(unittest.TestCase):
    """setattr-based monkeypatching with automatic restore."""

    def _patch(self, obj, name, value):
        original = getattr(obj, name)
        setattr(obj, name, original)  # sanity: attribute must already exist
        setattr(obj, name, value)
        self.addCleanup(setattr, obj, name, original)


class ReconcileLineTest(_PatchMixin):
    """_reconcile_line() assembles the 对账 line from reconcile_market rows."""

    def _run(self, rows_by_inst, markets=None):
        import daily_summary
        import okx_quant_lab.reconcile as reconcile_mod

        self._patch(
            reconcile_mod, "MARKETS", markets or ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
        )

        def fake_reconcile_market(inst_id, root):
            # The script must pass its own repo ROOT through.
            self.assertEqual(root, daily_summary.ROOT)
            return rows_by_inst.get(inst_id)

        self._patch(reconcile_mod, "reconcile_market", fake_reconcile_market)
        return daily_summary._reconcile_line()

    def test_all_rows_missing_reports_no_trades(self) -> None:
        line = self._run({})  # every market -> None (not deployed)
        self.assertEqual(line, "对账: 暂无成交")

    def test_ok_rows_below_thresholds_have_no_warning_flags(self) -> None:
        line = self._run(
            {
                "BTC-USDT": {"status": "ok", "flatter": 1.9, "equity_gap_pct": 0.9},
            },
            markets=["BTC-USDT"],
        )
        self.assertEqual(line, "对账: 成交比 BTC 1.9x | 权益差(纸面−实盘) BTC +0.9%")
        self.assertNotIn("⚠️", line)

    def test_flatter_at_threshold_triggers_fill_ratio_flag(self) -> None:
        line = self._run(
            {"SOL-USDT": {"status": "ok", "flatter": 2.0, "equity_gap_pct": 0.0}},
            markets=["SOL-USDT"],
        )
        self.assertIn("成交比 SOL 2.0x ⚠️成交比偏高", line)
        self.assertNotIn("⚠️纸面权益偏乐观", line)

    def test_gap_at_threshold_triggers_optimism_flag(self) -> None:
        line = self._run(
            {"ETH-USDT": {"status": "ok", "flatter": 1.0, "equity_gap_pct": 1.0}},
            markets=["ETH-USDT"],
        )
        self.assertIn("权益差(纸面−实盘) ETH +1.0% ⚠️纸面权益偏乐观", line)
        self.assertNotIn("⚠️成交比偏高", line)

    def test_negative_gap_does_not_trigger_optimism_flag(self) -> None:
        # Paper being PESSIMISTIC (negative gap) is fine; only optimism warns.
        line = self._run(
            {"BTC-USDT": {"status": "ok", "flatter": None, "equity_gap_pct": -3.5}},
            markets=["BTC-USDT"],
        )
        self.assertIn("BTC -3.5%", line)
        self.assertNotIn("⚠️", line)

    def test_none_flatter_skips_fill_ratio_but_keeps_gap(self) -> None:
        # demo had zero fills -> flatter is None -> no 成交比 section at all.
        line = self._run(
            {"BTC-USDT": {"status": "ok", "flatter": None, "equity_gap_pct": 0.2}},
            markets=["BTC-USDT"],
        )
        self.assertEqual(line, "对账: 权益差(纸面−实盘) BTC +0.2%")

    def test_mixed_rows_assemble_sections_in_order(self) -> None:
        # ok + insufficient_history + not-deployed(None) across the 3 markets.
        line = self._run(
            {
                "BTC-USDT": {"status": "ok", "flatter": 2.5, "equity_gap_pct": 0.4},
                "ETH-USDT": {"status": "insufficient_history"},
                # SOL-USDT absent -> None -> skipped silently
            }
        )
        self.assertEqual(
            line,
            "对账: 成交比 BTC 2.5x ⚠️成交比偏高"
            " | 权益差(纸面−实盘) BTC +0.4%"
            " | 历史不足: ETH",
        )

    def test_only_stale_markets_still_reports_them(self) -> None:
        line = self._run(
            {
                "BTC-USDT": {"status": "insufficient_history"},
                "SOL-USDT": {"status": "insufficient_history"},
            }
        )
        self.assertEqual(line, "对账: 历史不足: BTC, SOL")

    def test_unknown_status_rows_are_ignored(self) -> None:
        line = self._run(
            {"BTC-USDT": {"status": "weird", "flatter": 9.0, "equity_gap_pct": 9.0}},
            markets=["BTC-USDT"],
        )
        self.assertEqual(line, "对账: 暂无成交")

    def test_reconcile_error_is_reported_not_raised(self) -> None:
        import daily_summary
        import okx_quant_lab.reconcile as reconcile_mod

        def boom(inst_id, root):
            raise KeyError("levels")

        self._patch(reconcile_mod, "reconcile_market", boom)
        self.assertEqual(daily_summary._reconcile_line(), "对账: 计算失败 KeyError")


class _FakeCandle:
    def __init__(self, close: float) -> None:
        self.close = close


class PaperLineTest(_PatchMixin):
    """_paper_line() reads candles/state under ROOT and formats equities."""

    def _setup_fake_root(self, state_files=()):
        import daily_summary

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        fake_root = Path(tmp.name)
        (fake_root / "data" / "paper").mkdir(parents=True)
        for name in state_files:
            (fake_root / "data" / "paper" / name).write_text("{}")
        self._patch(daily_summary, "ROOT", fake_root)
        return daily_summary

    def test_reports_all_three_strategies_when_states_exist(self) -> None:
        ds = self._setup_fake_root(
            [
                "SOL-USDT_1H_state.json",
                "SOL-USDT_1H_grid_state.json",
                "ETH-USDT_1H_donchian_state.json",
            ]
        )
        seen = {}

        def fake_load_candles(path):
            # Last close is the mark: SOL -> 20.0, ETH -> 40.0.
            if "SOL" in path.name:
                return [_FakeCandle(10.0), _FakeCandle(20.0)]
            return [_FakeCandle(30.0), _FakeCandle(40.0)]

        def fake_sma_equity(state, close, cfg):
            seen["sma"] = (close, cfg.inst_id)
            return 1111.4

        def fake_grid_equity(state, close, cfg):
            seen["grid"] = (close, cfg.inst_id)
            return 987.0

        def fake_donchian_equity(state, close, cfg):
            seen["donchian"] = (close, cfg.inst_id)
            return 1049.6

        self._patch(ds, "load_candles_csv", fake_load_candles)
        self._patch(ds, "load_paper_state", lambda path: {"path": path.name})
        self._patch(ds, "load_grid_paper_state", lambda path: {"path": path.name})
        self._patch(ds, "paper_equity", fake_sma_equity)
        self._patch(ds, "grid_paper_equity", fake_grid_equity)
        self._patch(ds, "donchian_paper_equity", fake_donchian_equity)

        line = ds._paper_line()

        # :.0f rounding, comma-joined, in sma/grid/donchian order.
        self.assertEqual(line, "纸面策略(各1000起步): sma 1111, grid 987, donchian 1050")
        # SOL close feeds sma+grid, ETH close feeds donchian; configs carry inst_id.
        self.assertEqual(seen["sma"], (20.0, "SOL-USDT"))
        self.assertEqual(seen["grid"], (20.0, "SOL-USDT"))
        self.assertEqual(seen["donchian"], (40.0, "ETH-USDT"))

    def test_missing_state_files_yield_empty_strategy_list(self) -> None:
        ds = self._setup_fake_root(state_files=())
        self._patch(ds, "load_candles_csv", lambda path: [_FakeCandle(5.0)])

        # No state file exists -> every branch skipped -> bare prefix, no crash.
        self.assertEqual(ds._paper_line(), "纸面策略(各1000起步): ")

    def test_candle_read_failure_reports_error_type(self) -> None:
        ds = self._setup_fake_root(state_files=())

        def boom(path):
            raise ValueError("corrupt csv")

        self._patch(ds, "load_candles_csv", boom)
        self.assertEqual(ds._paper_line(), "纸面策略: 读取失败 ValueError")


if __name__ == "__main__":
    unittest.main()


class IdleGridNoteTest(unittest.TestCase):
    """A long-only grid holding nothing, with price outside its range, can
    never fill again — the condition behind '为什么这两天没成交' (2026-08-26)."""

    def _state(self, holdings, levels=None):
        import daily_summary  # noqa: F401  (ensures sys.path is set up)
        from okx_quant_lab.demo_grid import DemoGridConfig, new_demo_grid_state
        from dataclasses import replace

        base = new_demo_grid_state(
            DemoGridConfig(inst_id="SOL-USDT", range_pct=10.0, grid_count=4), 100.0
        )
        return replace(base, holdings=list(holdings), levels=levels or base.levels)

    def _note(self, *args, **kwargs):
        import daily_summary

        return daily_summary._idle_grid_note(*args, **kwargs)

    def test_above_range_and_empty_is_flagged_with_the_move_needed(self) -> None:
        state = self._state([0.0, 0.0, 0.0, 0.0], levels=[90.0, 95.0, 100.0, 105.0, 110.0])
        note = self._note("SOL-USDT", state, 121.0, [], 1_000_000)

        self.assertIsNotNone(note)
        self.assertIn("SOL", note)
        self.assertIn("-9.1%", note)  # 110 / 121 - 1
        self.assertIn("从未成交", note)

    def test_below_range_and_empty_is_not_idle_it_buys_next_bar(self) -> None:
        # Below the range every armed level satisfies close <= level, so an
        # empty grid there acts on the next candle — flagging it as "can never
        # fill again" would be wrong (found in the 2026-08-27 review).
        state = self._state([0.0] * 4, levels=[90.0, 95.0, 100.0, 105.0, 110.0])
        self.assertIsNone(self._note("SOL-USDT", state, 45.0, [], 1_000_000))

    def test_holding_inventory_is_never_idle(self) -> None:
        state = self._state([0.0, 1.0, 0.0, 0.0], levels=[90.0, 95.0, 100.0, 105.0, 110.0])
        self.assertIsNone(self._note("SOL-USDT", state, 121.0, [], 1_000_000))

    def test_price_inside_range_is_never_idle(self) -> None:
        state = self._state([0.0] * 4, levels=[90.0, 95.0, 100.0, 105.0, 110.0])
        self.assertIsNone(self._note("SOL-USDT", state, 99.0, [], 1_000_000))

    def test_days_since_last_fill_uses_the_newest_fill(self) -> None:
        from okx_quant_lab.demo_execution import DemoOrderRecord
        from okx_quant_lab.dry_run import OrderRequest

        def record(status, created_at_ms):
            return DemoOrderRecord(
                request=OrderRequest(
                    client_order_id=f"x{created_at_ms}", inst_id="SOL-USDT", side="SELL",
                    quote_amount_usdt=0.0, base_quantity=1.0, reference_price=100.0,
                    created_at_ms=created_at_ms, reason="test",
                ),
                status=status, exchange_order_id="", exchange_client_order_id="",
                fill_price=100.0, fill_quantity=1.0, fee=0.0, fee_currency="", message="",
            )

        day = 86_400_000
        now = 10 * day
        records = [
            record("FILLED", 3 * day),
            record("FILLED", 6 * day),   # newest FILL -> 4.0 days ago
            record("CANCELED", 9 * day),  # not a fill, must be ignored
        ]
        state = self._state([0.0] * 4, levels=[90.0, 95.0, 100.0, 105.0, 110.0])
        note = self._note("SOL-USDT", state, 121.0, records, now)

        self.assertIn("4.0 天前", note)
