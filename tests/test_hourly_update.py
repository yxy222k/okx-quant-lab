from __future__ import annotations

import contextlib
import io
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# Import-time work in the script is only a sys.path bootstrap plus pure
# okx_quant_lab imports (main() is guarded), so a top-level import is safe.
import hourly_update

from okx_quant_lab import candle_store
from okx_quant_lab.okx_public import Candle


HOUR_MS = 60 * 60 * 1_000


def _flat_candles(
    count: int,
    end_ms: int,
    price: float = 100.0,
    last_low: float | None = None,
) -> list[Candle]:
    """Hourly candles pinned at `price`, ending at end_ms.

    Flat closes mean the SMA cross, the Donchian breakout, and the grid all
    stay quiet — zero fills — unless `last_low` dips the final candle's low
    (which triggers grid buys while every close stays at `price`).
    """
    candles = []
    for i in range(count):
        ts = end_ms - (count - 1 - i) * HOUR_MS
        low = price
        if last_low is not None and i == count - 1:
            low = last_low
        candles.append(
            Candle(
                timestamp_ms=ts,
                open=price,
                high=price,
                low=low,
                close=price,
                volume_base=1.0,
                volume_quote=price,
                confirmed=True,
            )
        )
    return candles


class TempRootTestCase(unittest.TestCase):
    """Every path the script touches is re-rooted into a tempdir."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)


class SeenAtTest(unittest.TestCase):
    def test_epoch_renders_as_utc_iso(self) -> None:
        self.assertEqual(hourly_update._seen_at(0), "1970-01-01T00:00:00+00:00")

    def test_known_timestamp_renders_in_utc_not_local_time(self) -> None:
        self.assertEqual(
            hourly_update._seen_at(1_700_000_000_000), "2023-11-14T22:13:20+00:00"
        )


class WriteReportTest(TempRootTestCase):
    def test_report_body_is_exactly_the_header_plus_fenced_lines(self) -> None:
        with mock.patch.object(hourly_update, "ROOT", self.root):
            hourly_update._write_report(["alpha", "beta"], 1_700_000_000_000)

        report_path = self.root / "reports" / "hourly_update_report.md"
        self.assertTrue(report_path.exists())
        self.assertEqual(
            report_path.read_text(encoding="utf-8"),
            "# Hourly Paper Update\n"
            "\n"
            "Generated at UTC: 2023-11-14T22:13:20+00:00\n"
            "\n"
            "```\n"
            "alpha\n"
            "beta\n"
            "```\n",
        )


class RefreshCandlesWiringTest(TempRootTestCase):
    def test_passes_scan_path_bar_target_and_retention_constant(self) -> None:
        seen: dict = {}
        sentinel = _flat_candles(3, 1_700_000_000_000)

        def fake_refresh(path, inst_id, bar=None, target_count=None, retention=None):
            seen.update(
                path=Path(path),
                inst_id=inst_id,
                bar=bar,
                target_count=target_count,
                retention=retention,
            )
            return sentinel

        with mock.patch.object(hourly_update, "ROOT", self.root), mock.patch.object(
            hourly_update, "refresh_candles", fake_refresh
        ):
            result = hourly_update._refresh_candles("SOL-USDT")

        self.assertIs(result, sentinel)
        self.assertEqual(
            seen["path"], self.root / "data" / "candles" / "SOL-USDT_1H_scan.csv"
        )
        self.assertEqual(seen["inst_id"], "SOL-USDT")
        self.assertEqual(seen["bar"], "1H")
        self.assertEqual(seen["target_count"], 300)
        self.assertEqual(seen["retention"], hourly_update.CANDLE_RETENTION_1H)
        self.assertEqual(hourly_update.CANDLE_RETENTION_1H, 12_000)

    def test_retention_constant_is_applied_by_the_real_store(self) -> None:
        # Route _refresh_candles through the real candle_store.refresh_candles
        # with injected fetchers: the saved window must be trimmed to exactly
        # CANDLE_RETENTION_1H rows, keeping the newest candles.
        retention = hourly_update.CANDLE_RETENTION_1H
        overflow = 50
        fetched = _flat_candles(retention + overflow, 1_700_000_000_000)
        history_calls: list[str] = []

        def fake_latest(inst_id, bar="1H", limit=200):
            return fetched

        def fake_history(inst_id, bar="1H", target_count=300):
            history_calls.append(inst_id)
            return []

        def wired_refresh(path, inst_id, bar="1H", target_count=300, retention=None):
            return candle_store.refresh_candles(
                path,
                inst_id,
                bar=bar,
                target_count=target_count,
                retention=retention,
                fetch_latest=fake_latest,
                fetch_history=fake_history,
            )

        with mock.patch.object(hourly_update, "ROOT", self.root), mock.patch.object(
            hourly_update, "refresh_candles", wired_refresh
        ):
            result = hourly_update._refresh_candles("SOL-USDT")

        self.assertEqual(len(result), retention)
        # The trim drops the OLDEST candles, never the newest.
        self.assertEqual(result[0].timestamp_ms, fetched[overflow].timestamp_ms)
        self.assertEqual(result[-1].timestamp_ms, fetched[-1].timestamp_ms)
        # Enough candles came from "latest"; the pager must not run.
        self.assertEqual(history_calls, [])

        csv_path = self.root / "data" / "candles" / "SOL-USDT_1H_scan.csv"
        rows = csv_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(rows) - 1, retention)  # header + retention rows


class RunUpdateTest(TempRootTestCase):
    def _run(self, sol_candles, eth_candles):
        calls = []

        def fake_refresh(path, inst_id, bar=None, target_count=None, retention=None):
            calls.append({"inst_id": inst_id, "retention": retention, "path": Path(path)})
            return {"SOL-USDT": sol_candles, "ETH-USDT": eth_candles}[inst_id]

        with mock.patch.object(hourly_update, "ROOT", self.root), mock.patch.object(
            hourly_update, "refresh_candles", fake_refresh
        ):
            lines, attention, has_failures = hourly_update._run_update()
        return lines, attention, has_failures, calls

    @staticmethod
    def _fresh_end_ms() -> int:
        return int(time.time() * 1000) - 30 * 60 * 1000  # 0.5h old: fresh

    def test_quiet_hour_all_checks_pass_and_no_attention(self) -> None:
        end_ms = self._fresh_end_ms()
        lines, attention, has_failures, calls = self._run(
            _flat_candles(60, end_ms), _flat_candles(60, end_ms)
        )

        self.assertFalse(has_failures)
        self.assertFalse(attention)

        self.assertTrue(lines[0].startswith("OKX quant hourly update @ "))
        self.assertEqual(
            lines[1], "safety: public data only, no API keys, no orders submitted."
        )

        sma_line = next(line for line in lines if line.startswith("sma(SOL):"))
        grid_line = next(line for line in lines if line.startswith("grid(SOL):"))
        donchian_line = next(line for line in lines if line.startswith("donchian(ETH):"))
        # Flat prices: nobody trades and equity stays at initial cash.
        self.assertIn("equity=1000.00", sma_line)
        self.assertIn("new_fills=0", sma_line)
        self.assertIn("new_fills=0 open_slots=0 realized=0.00", grid_line)
        self.assertIn("new_fills=0", donchian_line)

        pass_lines = [line for line in lines if line.startswith("[PASS]")]
        fail_lines = [line for line in lines if line.startswith("[FAIL]")]
        self.assertEqual(len(pass_lines), 6)  # 2 freshness + 3 caught-up + grid range
        self.assertEqual(fail_lines, [])

        # Both instruments refreshed with the shared retention constant.
        self.assertEqual([call["inst_id"] for call in calls], ["SOL-USDT", "ETH-USDT"])
        self.assertEqual(
            {call["retention"] for call in calls}, {hourly_update.CANDLE_RETENTION_1H}
        )

        # States and report land under the (re-rooted) tree, not the repo.
        paper_dir = self.root / "data" / "paper"
        self.assertTrue((paper_dir / "SOL-USDT_1H_state.json").exists())
        self.assertTrue((paper_dir / "SOL-USDT_1H_grid_state.json").exists())
        self.assertTrue((paper_dir / "ETH-USDT_1H_donchian_state.json").exists())
        report = (self.root / "reports" / "hourly_update_report.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("\n".join(lines), report)

    def test_stale_candles_fail_freshness_and_raise_attention(self) -> None:
        end_ms = int(time.time() * 1000) - 3 * HOUR_MS  # older than max_age_hours=2
        lines, attention, has_failures, _ = self._run(
            _flat_candles(60, end_ms), _flat_candles(60, end_ms)
        )

        self.assertTrue(has_failures)
        self.assertTrue(attention)
        fail_lines = [line for line in lines if line.startswith("[FAIL]")]
        self.assertEqual(len(fail_lines), 2)
        self.assertTrue(any("SOL-USDT candles" in line for line in fail_lines))
        self.assertTrue(any("ETH-USDT candles" in line for line in fail_lines))
        # The paper states still caught up to the (stale) candles.
        self.assertEqual(len([line for line in lines if line.startswith("[PASS]")]), 4)

    def test_new_fills_need_attention_even_with_all_checks_passing(self) -> None:
        end_ms = self._fresh_end_ms()
        # Last SOL candle dips to 80: all 5 armed grid levels (85..97) buy,
        # while the close stays 100 so every check still passes.
        sol = _flat_candles(60, end_ms, last_low=80.0)
        lines, attention, has_failures, _ = self._run(sol, _flat_candles(60, end_ms))

        self.assertFalse(has_failures)
        self.assertTrue(attention)  # attention from fills alone
        grid_line = next(line for line in lines if line.startswith("grid(SOL):"))
        self.assertIn("new_fills=5 open_slots=5", grid_line)

    def test_second_run_reloads_state_and_goes_quiet(self) -> None:
        end_ms = self._fresh_end_ms()
        sol = _flat_candles(60, end_ms, last_low=80.0)
        eth = _flat_candles(60, end_ms)

        _, first_attention, _, _ = self._run(sol, eth)
        self.assertTrue(first_attention)

        # Same candles again: everything is at/behind the checkpoint, so the
        # reloaded states report no new fills but keep the open inventory.
        lines, attention, has_failures, _ = self._run(sol, eth)
        self.assertFalse(attention)
        self.assertFalse(has_failures)
        grid_line = next(line for line in lines if line.startswith("grid(SOL):"))
        self.assertIn("new_fills=0 open_slots=5", grid_line)


class MainTest(unittest.TestCase):
    def _call_main(self, argv, run_update):
        buffer = io.StringIO()
        with mock.patch.object(sys, "argv", ["hourly_update.py", *argv]), mock.patch.object(
            hourly_update, "_run_update", run_update
        ), contextlib.redirect_stdout(buffer):
            code = hourly_update.main()
        return code, buffer.getvalue()

    def test_normal_mode_prints_and_exits_zero_when_healthy(self) -> None:
        code, out = self._call_main([], lambda: (["a", "b"], False, False))
        self.assertEqual(code, 0)
        self.assertEqual(out, "a\nb\n")

    def test_normal_mode_exits_one_on_failed_checks(self) -> None:
        code, out = self._call_main([], lambda: (["bad"], True, True))
        self.assertEqual(code, 1)
        self.assertEqual(out, "bad\n")

    def test_watchdog_is_silent_on_boring_hours(self) -> None:
        code, out = self._call_main(["--watchdog"], lambda: (["quiet"], False, False))
        self.assertEqual(code, 0)
        self.assertEqual(out, "")

    def test_watchdog_prints_when_attention_needed_but_still_exits_zero(self) -> None:
        code, out = self._call_main(["--watchdog"], lambda: (["fills!"], True, True))
        self.assertEqual(code, 0)
        self.assertEqual(out, "fills!\n")

    def _boom(self):
        raise RuntimeError("boom")

    def test_update_error_is_reported_and_fails_normal_mode(self) -> None:
        code, out = self._call_main([], lambda: self._boom())
        self.assertEqual(code, 1)
        self.assertEqual(out, "OKX quant hourly update FAILED: RuntimeError: boom\n")

    def test_update_error_keeps_watchdog_exit_zero_but_reports(self) -> None:
        code, out = self._call_main(["--watchdog"], lambda: self._boom())
        self.assertEqual(code, 0)
        self.assertEqual(out, "OKX quant hourly update FAILED: RuntimeError: boom\n")


if __name__ == "__main__":
    unittest.main()
