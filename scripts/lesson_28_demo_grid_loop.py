#!/usr/bin/env python3
"""15-minute demo-trading grid loop across multiple markets.

For each market, advances a close-confirmed grid on fresh public 15m candles
and routes every triggered order through the demo executor (safety gates,
notional cap, per-market ledger). Requires --confirm as the standing
authorization to submit demo orders; without it every order is BLOCKED by
the Lesson 12 gate.

--watchdog prints only when something happened (orders, circuit breaker,
errors) and always exits 0, for Hermes cron delivery.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.candle_store import refresh_candles
from okx_quant_lab.demo_execution import (
    DemoExecutionLimits,
    DemoOrderExecutor,
    load_demo_order_ledger,
    save_demo_order_ledger,
)
from okx_quant_lab.demo_grid import (
    DemoGridConfig,
    advance_demo_grid,
    demo_grid_equity,
    load_demo_grid_state,
    new_demo_grid_state,
    open_slot_count,
    save_demo_grid_state,
)
from okx_quant_lab.okx_demo_private import load_demo_credentials
from okx_quant_lab.okx_public import fetch_instrument_spec


BAR = "15m"
MARKETS = ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
LIMITS = DemoExecutionLimits(max_order_usdt=25.0)
CANDLE_RETENTION = 12_000


def market_config(inst_id: str) -> DemoGridConfig:
    return DemoGridConfig(
        inst_id=inst_id,
        range_pct=15.0,
        grid_count=20,
        allocation_usdt=100.0,
        max_daily_loss_pct=3.0,
    )


def state_path(inst_id: str) -> Path:
    return ROOT / "data" / "demo" / f"{inst_id}_{BAR}_demo_grid_state.json"


def ledger_path(inst_id: str) -> Path:
    return ROOT / "data" / "orders" / f"demo_grid_orders_{inst_id}.json"


def candle_path(inst_id: str) -> Path:
    return ROOT / "data" / "candles" / f"{inst_id}_{BAR}_demo.csv"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", action="store_true",
                        help="standing authorization to submit demo orders")
    parser.add_argument("--watchdog", action="store_true",
                        help="print only when something happened; always exit 0")
    args = parser.parse_args()

    lines: list[str] = []
    attention = False
    failed = False
    credentials = None
    try:
        credentials = load_demo_credentials()
    except Exception as error:
        print(f"demo grid loop FAILED: {type(error).__name__}: {error}")
        return 0 if args.watchdog else 1

    for inst_id in MARKETS:
        try:
            market_lines, market_attention = _run_market(inst_id, credentials, args.confirm)
        except Exception as error:
            lines.append(f"{inst_id}: FAILED {type(error).__name__}: {error}")
            attention = True
            failed = True
            continue
        lines.extend(market_lines)
        attention = attention or market_attention

    if args.watchdog:
        if attention:
            print("\n".join(lines))
        return 0

    print("\n".join(lines))
    return 1 if failed else 0


def _run_market(inst_id: str, credentials, confirmed: bool) -> tuple[list[str], bool]:
    config = market_config(inst_id)
    # Retain enough history to cover the whole demo phase so reconcile_grids can
    # always replay from the deploy candle. 12000 15m bars ~= 125 days (~1 MB CSV).
    candles = refresh_candles(
        candle_path(inst_id), inst_id, bar=BAR, target_count=300, retention=CANDLE_RETENTION
    )

    spec = fetch_instrument_spec(inst_id)
    records = load_demo_order_ledger(ledger_path(inst_id)) if ledger_path(inst_id).exists() else []
    executor = DemoOrderExecutor(credentials, LIMITS, records=records)

    deployed_now = not state_path(inst_id).exists()
    if deployed_now:
        # A new grid anchors at the CURRENT price and starts from the CURRENT
        # candle. Historical candles must never replay as live market orders.
        state = new_demo_grid_state(config, reference_price=candles[-1].close)
        state = replace(
            state,
            last_timestamp_ms=candles[-1].timestamp_ms,
            deploy_timestamp_ms=candles[-1].timestamp_ms,
        )
    else:
        state = load_demo_grid_state(state_path(inst_id))

    state, events = advance_demo_grid(candles, state, config, executor, spec, confirmed)
    save_demo_grid_state(state_path(inst_id), state)
    save_demo_order_ledger(ledger_path(inst_id), executor.records)

    mark = candles[-1].close
    equity = demo_grid_equity(state, mark)
    attention = bool(events) or state.breaker_tripped

    lines = []
    if deployed_now:
        lines.append(
            f"{inst_id}: deployed grid {state.levels[0]:.4f}..{state.levels[-1]:.4f} "
            f"({config.grid_count} slots x {config.slot_cash:.2f} USDT, {BAR} bars)"
        )
        attention = True
    lines.extend(f"{inst_id}: {event}" for event in events)
    lines.append(
        f"{inst_id}: equity={equity:.2f}/{config.allocation_usdt:.2f} "
        f"open={open_slot_count(state)}/{config.grid_count} "
        f"realized={state.realized_profit:.2f} mark={mark:.4f} "
        f"breaker={'TRIPPED' if state.breaker_tripped else 'ok'}"
        + (f" @ {_seen_at(candles[-1].timestamp_ms)}" if attention else "")
    )
    if mark < state.levels[0]:
        lines.append(f"{inst_id}: WARNING mark {mark:.4f} below grid range {state.levels[0]:.4f}")
        attention = True

    return lines, attention


def _seen_at(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
