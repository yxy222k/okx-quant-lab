#!/usr/bin/env python3
"""Advance every paper strategy on fresh public data and run monitoring.

Normal mode prints a full status block and exits 1 if any check fails.
Watchdog mode (--watchdog) prints ONLY when something needs attention
(new fills, failed checks, or an update error) and always exits 0, so a
scheduler like Hermes cron can deliver stdout verbatim and stay silent
on boring hours.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.candle_store import refresh_candles
from okx_quant_lab.donchian_paper import (
    DonchianPaperConfig,
    donchian_paper_equity,
    new_donchian_paper_state,
    run_donchian_paper_session,
)
from okx_quant_lab.grid_paper import (
    GridPaperConfig,
    grid_paper_equity,
    load_grid_paper_state,
    new_grid_paper_state,
    open_slot_count,
    run_grid_paper_session,
    save_grid_paper_state,
)
from okx_quant_lab.monitoring import (
    MonitorCheck,
    check_candle_freshness,
    check_grid_price_in_range,
    check_grid_state_caught_up,
    check_paper_state_caught_up,
)
from okx_quant_lab.paper import (
    PaperConfig,
    load_paper_state,
    new_paper_state,
    paper_equity,
    run_paper_session,
    save_paper_state,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--watchdog",
        action="store_true",
        help="print only when attention is needed; always exit 0",
    )
    args = parser.parse_args()

    try:
        lines, attention, has_failures = _run_update()
    except Exception as error:  # network or data trouble is exactly what to report
        print(f"OKX quant hourly update FAILED: {type(error).__name__}: {error}")
        return 0 if args.watchdog else 1

    if args.watchdog:
        if attention:
            print("\n".join(lines))
        return 0

    print("\n".join(lines))
    return 1 if has_failures else 0


def _run_update() -> tuple[list[str], bool, bool]:
    sol_candles = _refresh_candles("SOL-USDT")
    eth_candles = _refresh_candles("ETH-USDT")
    now_ms = int(time.time() * 1000)

    status_lines: list[str] = []
    checks: list[MonitorCheck] = [
        check_candle_freshness("SOL-USDT", sol_candles, now_ms, max_age_hours=2.0),
        check_candle_freshness("ETH-USDT", eth_candles, now_ms, max_age_hours=2.0),
    ]
    new_fill_total = 0

    # SMA paper on SOL-USDT (Lesson 11 state).
    sma_config = PaperConfig(inst_id="SOL-USDT")
    sma_path = ROOT / "data" / "paper" / "SOL-USDT_1H_state.json"
    sma_state = load_paper_state(sma_path) if sma_path.exists() else new_paper_state(sma_config)
    sma_before = len(sma_state.fills)
    sma_state = run_paper_session(sol_candles, sma_state, sma_config)
    save_paper_state(sma_path, sma_state)
    sma_new = len(sma_state.fills) - sma_before
    new_fill_total += sma_new
    checks.append(check_paper_state_caught_up(sma_state, sol_candles))
    status_lines.append(
        f"sma(SOL):      equity={paper_equity(sma_state, sol_candles[-1].close, sma_config):.2f} "
        f"new_fills={sma_new}"
    )

    # Grid paper on SOL-USDT (Lesson 22 state).
    grid_config = GridPaperConfig(inst_id="SOL-USDT")
    grid_path = ROOT / "data" / "paper" / "SOL-USDT_1H_grid_state.json"
    if grid_path.exists():
        grid_state = load_grid_paper_state(grid_path)
    else:
        grid_state = new_grid_paper_state(grid_config, reference_price=sol_candles[0].open)
    grid_before = len(grid_state.fills)
    grid_state = run_grid_paper_session(sol_candles, grid_state, grid_config)
    save_grid_paper_state(grid_path, grid_state)
    grid_new = len(grid_state.fills) - grid_before
    new_fill_total += grid_new
    checks.append(check_grid_state_caught_up(grid_state, sol_candles))
    checks.append(check_grid_price_in_range(grid_state, sol_candles))
    status_lines.append(
        f"grid(SOL):     equity={grid_paper_equity(grid_state, sol_candles[-1].close, grid_config):.2f} "
        f"new_fills={grid_new} open_slots={open_slot_count(grid_state)} "
        f"realized={grid_state.realized_profit:.2f}"
    )

    # Donchian paper on ETH-USDT (Lesson 24 state).
    donchian_config = DonchianPaperConfig(inst_id="ETH-USDT")
    donchian_path = ROOT / "data" / "paper" / "ETH-USDT_1H_donchian_state.json"
    donchian_state = (
        load_paper_state(donchian_path)
        if donchian_path.exists()
        else new_donchian_paper_state(donchian_config)
    )
    donchian_before = len(donchian_state.fills)
    donchian_state = run_donchian_paper_session(eth_candles, donchian_state, donchian_config)
    save_paper_state(donchian_path, donchian_state)
    donchian_new = len(donchian_state.fills) - donchian_before
    new_fill_total += donchian_new
    checks.append(check_paper_state_caught_up(donchian_state, eth_candles))
    status_lines.append(
        f"donchian(ETH): equity="
        f"{donchian_paper_equity(donchian_state, eth_candles[-1].close, donchian_config):.2f} "
        f"new_fills={donchian_new}"
    )

    has_failures = any(not check.passed for check in checks)
    attention = has_failures or new_fill_total > 0

    lines = [
        f"OKX quant hourly update @ {_seen_at(now_ms)}",
        "safety: public data only, no API keys, no orders submitted.",
    ]
    lines.extend(status_lines)
    for check in checks:
        flag = "PASS" if check.passed else "FAIL"
        lines.append(f"[{flag}] {check.name}: {check.message}")

    _write_report(lines, now_ms)
    return lines, attention, has_failures


def _refresh_candles(inst_id: str) -> list:
    path = ROOT / "data" / "candles" / f"{inst_id}_1H_scan.csv"
    return refresh_candles(path, inst_id, bar="1H", target_count=300)


def _write_report(lines: list[str], now_ms: int) -> None:
    report_path = ROOT / "reports" / "hourly_update_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    body = [
        "# Hourly Paper Update",
        "",
        f"Generated at UTC: {_seen_at(now_ms)}",
        "",
        "```",
        *lines,
        "```",
        "",
    ]
    report_path.write_text("\n".join(body), encoding="utf-8")


def _seen_at(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
