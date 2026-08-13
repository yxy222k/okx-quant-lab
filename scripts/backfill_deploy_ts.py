#!/usr/bin/env python3
"""One-time migration: freeze deploy_timestamp_ms into demo grid states that
predate the field. Uses the midpoint inference (still accurate while the deploy
candle is on file) to recover the deploy candle, then persists it so future
reconciliation is anchored rather than inferred. Idempotent: skips any state
whose deploy_timestamp_ms is already set.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.candle_store import load_candles_csv
from okx_quant_lab.demo_execution import load_demo_order_ledger
from okx_quant_lab.demo_grid import load_demo_grid_state, save_demo_grid_state

BAR = "15m"
MARKETS = ["BTC-USDT", "ETH-USDT", "SOL-USDT"]


def main() -> int:
    for inst_id in MARKETS:
        state_path = ROOT / "data" / "demo" / f"{inst_id}_{BAR}_demo_grid_state.json"
        candle_file = ROOT / "data" / "candles" / f"{inst_id}_{BAR}_demo.csv"
        ledger_file = ROOT / "data" / "orders" / f"demo_grid_orders_{inst_id}.json"

        if not state_path.exists():
            print(f"{inst_id}: no state, skip")
            continue
        state = load_demo_grid_state(state_path)
        if state.deploy_timestamp_ms > 0:
            print(f"{inst_id}: already set ({_utc(state.deploy_timestamp_ms)}), skip")
            continue
        if not candle_file.exists():
            print(f"{inst_id}: no candle file, cannot infer, skip")
            continue

        candles = load_candles_csv(candle_file)
        if not candles:
            print(f"{inst_id}: empty candle file, cannot infer, skip")
            continue
        records = load_demo_order_ledger(ledger_file) if ledger_file.exists() else []
        filled = [r for r in records if r.status == "FILLED"]
        ref = (state.levels[0] + state.levels[-1]) / 2
        first_fill_ts = min((r.request.created_at_ms for r in filled), default=None)
        pre = [c for c in candles if first_fill_ts is None or c.timestamp_ms <= first_fill_ts]
        pool = pre or candles
        # The deploy candle's close equals ref to float precision. Price can
        # revisit that exact tick, giving several matches; the deploy is the
        # LATEST match at/before the first fill (the most recent anchor before
        # trading began — earlier same-price candles are pre-deploy history).
        # min-by-distance alone would wrongly pick the earliest revisit.
        matches = [c for c in pool if abs(c.close - ref) <= ref * 1e-6]
        deploy = (
            max(matches, key=lambda c: c.timestamp_ms)
            if matches
            else min(pool, key=lambda c: abs(c.close - ref))
        )

        # The TRUE deploy candle's close equals the level midpoint to float
        # precision (the levels were computed from reference_price == that
        # close, and midpoint of a symmetric +-p% grid == reference_price
        # exactly). Any OTHER candle — including one the market revisits near
        # the midpoint after the real deploy candle was trimmed off — differs by
        # a real market amount (>= one tick). So a near-float-equality check is
        # a genuine "is THE deploy candle present" test, not a loose proximity
        # heuristic. Refuse rather than mis-anchor. (The old candles[0] > deploy
        # guard was dead code: deploy is chosen FROM the file, always >= it.)
        if (first_fill_ts is not None and not pre) or abs(deploy.close - ref) > ref * 1e-6:
            print(f"{inst_id}: deploy candle not on file to float precision "
                  f"(nearest close {deploy.close:.6f} vs ref {ref:.6f}) — skip, "
                  f"anchor unreliable")
            continue

        save_demo_grid_state(state_path, replace(state, deploy_timestamp_ms=deploy.timestamp_ms))
        print(f"{inst_id}: set deploy_timestamp_ms = {deploy.timestamp_ms} "
              f"({_utc(deploy.timestamp_ms)}, close {deploy.close:.4f} vs ref {ref:.4f})")
    return 0


def _utc(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
