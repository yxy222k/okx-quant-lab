#!/usr/bin/env python3
"""Demo-phase result report: replay the order ledger to get the numbers the
live state files never keep — an equity curve, max drawdown, and the buy-and-hold
benchmark over the same window.

The grid state stores a snapshot (cash, holdings, realized), not a history, so
"what was the worst drawdown" cannot be answered from it. This rebuilds the
book from FILLED ledger records marked against the demo candles, using the same
accounting as advance_demo_grid: a buy spends one slot of cash, a sell credits
proceeds net of the quote-currency fee.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.candle_store import load_candles_csv
from okx_quant_lab.demo_execution import load_demo_order_ledger
from okx_quant_lab.demo_grid import load_demo_grid_state

MARKETS = ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
BAR = "15m"
ALLOCATION = 100.0
GRID_COUNT = 20


def replay_market(inst_id: str) -> dict | None:
    """Reconstruct one market's equity curve; None when it is not deployed."""
    state_path = ROOT / "data" / "demo" / f"{inst_id}_{BAR}_demo_grid_state.json"
    candle_path = ROOT / "data" / "candles" / f"{inst_id}_{BAR}_demo.csv"
    ledger_path = ROOT / "data" / "orders" / f"demo_grid_orders_{inst_id}.json"
    if not state_path.exists() or not candle_path.exists():
        return None

    state = load_demo_grid_state(state_path)
    candles = [
        c for c in load_candles_csv(candle_path)
        if c.timestamp_ms >= state.deploy_timestamp_ms
    ]
    if not candles:
        return None

    base, quote = inst_id.split("-")
    slot_cash = ALLOCATION / GRID_COUNT
    fills_by_ts: dict[int, list] = {}
    total_filled = partial_count = 0
    if ledger_path.exists():
        for record in load_demo_order_ledger(ledger_path):
            if record.status == "FILLED":
                total_filled += 1
                fills_by_ts.setdefault(record.request.created_at_ms, []).append(record)
            elif record.status == "PARTIAL":
                # The executor itself marks these "local book has drifted" —
                # a replay over a drifted book must say so, not average it away.
                partial_count += 1

    cash, holdings = ALLOCATION, 0.0
    buys = sells = 0
    matched = 0
    curve: list[tuple[int, float]] = []
    peak = max_drawdown = 0.0
    drawdown_at = candles[0].timestamp_ms

    for candle in candles:
        for record in fills_by_ts.get(candle.timestamp_ms, []):
            matched += 1
            if record.request.side == "BUY":
                cash -= slot_cash
                holdings += record.fill_quantity + (
                    record.fee if record.fee_currency == base else 0.0
                )
                buys += 1
            else:
                cash += record.fill_quantity * record.fill_price + (
                    record.fee if record.fee_currency == quote else 0.0
                )
                holdings -= record.fill_quantity
                sells += 1

        equity = cash + holdings * candle.close
        curve.append((candle.timestamp_ms, equity))
        peak = max(peak, equity) if curve[:-1] else equity
        drawdown = (equity / peak - 1) * 100
        if drawdown < max_drawdown:
            max_drawdown, drawdown_at = drawdown, candle.timestamp_ms

    # A fill whose trigger candle is missing from the CSV would silently
    # corrupt cash/holdings for the whole rest of the curve — the same
    # silent-gap failure mode candle_gaps() exists to catch.
    if matched != total_filled:
        print(
            f"warning: {inst_id}: only {matched}/{total_filled} FILLED records "
            f"matched a candle; the replay curve is NOT trustworthy",
            file=sys.stderr,
        )
    if partial_count:
        print(
            f"warning: {inst_id}: {partial_count} PARTIAL record(s) in the ledger — "
            f"the live book has drifted from the exchange; treat all numbers as approximate",
            file=sys.stderr,
        )

    # The live book discards sub-lot dust at each sell (the slot is zeroed
    # after selling only the lot-quantized quantity); this replay cannot know
    # per-slot dust from the ledger alone, so it reconciles against the live
    # state instead of pretending the difference is zero.
    live_equity = state.cash + sum(state.holdings) * candles[-1].close
    replay_equity = curve[-1][1]

    return {
        "inst_id": inst_id,
        "curve": curve,
        "matched": matched,
        "total_filled": total_filled,
        "partial_count": partial_count,
        "live_equity": live_equity,
        "replay_gap": replay_equity - live_equity,
        "buys": buys,
        "sells": sells,
        "final_equity": curve[-1][1],
        "peak_equity": max(equity for _, equity in curve),
        "max_drawdown_pct": max_drawdown,
        "drawdown_at_ms": drawdown_at,
        "deploy_ms": state.deploy_timestamp_ms,
        "last_ms": candles[-1].timestamp_ms,
        "buy_hold_pct": (candles[-1].close / candles[0].open - 1) * 100,
        "upper": state.levels[-1],
        "above_top_pct": (candles[-1].close / state.levels[-1] - 1) * 100,
        "open_slots": sum(1 for quantity in state.holdings if quantity > 0),
    }


def main() -> int:
    rows = [row for row in (replay_market(inst_id) for inst_id in MARKETS) if row]
    if not rows:
        print("no deployed grids to report on")
        return 1

    print("Demo phase report (replayed from the order ledger)")
    print(
        f"{'market':<9} {'days':>5} {'trips':>6} {'return%':>8} {'maxDD%':>7} "
        f"{'b&h%':>7} {'slots':>6}  state"
    )
    for row in rows:
        days = (row["last_ms"] - row["deploy_ms"]) / 86_400_000
        trips = min(row["buys"], row["sells"])
        idle = row["open_slots"] == 0 and row["above_top_pct"] > 0
        print(
            f"{row['inst_id']:<9} {days:>5.1f} {trips:>6} "
            f"{(row['final_equity'] / ALLOCATION - 1) * 100:>+8.2f} "
            f"{row['max_drawdown_pct']:>7.2f} {row['buy_hold_pct']:>+7.2f} "
            f"{row['open_slots']:>2}/{GRID_COUNT}  "
            + (f"IDLE, {row['above_top_pct']:+.1f}% above range" if idle else "active")
            + (f"  [replay-live gap {row['replay_gap']:+.3f} = discarded dust/booking drift]"
               if abs(row['replay_gap']) > 0.005 else "")
        )

    timestamps = sorted(set.intersection(*[{ts for ts, _ in r["curve"]} for r in rows]))
    equity_maps = [dict(r["curve"]) for r in rows]
    peak = max_drawdown = 0.0
    worst_at = timestamps[0]
    for index, timestamp in enumerate(timestamps):
        equity = sum(m[timestamp] for m in equity_maps)
        peak = max(peak, equity) if index else equity
        drawdown = (equity / peak - 1) * 100
        if drawdown < max_drawdown:
            max_drawdown, worst_at = drawdown, timestamp

    total_alloc = ALLOCATION * len(rows)
    final = sum(m[timestamps[-1]] for m in equity_maps)
    print()
    print(
        f"portfolio ({total_alloc:.0f} USDT): final {final:.2f} "
        f"({(final / total_alloc - 1) * 100:+.2f}%), max drawdown {max_drawdown:.2f}% "
        f"at {datetime.fromtimestamp(worst_at / 1000, tz=timezone.utc):%Y-%m-%d %H:%M} UTC"
    )
    print()
    print("A grid's return is capped by its range; buy & hold is the benchmark it")
    print("gives up to earn round trips. Compare the two columns, not the sign.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
