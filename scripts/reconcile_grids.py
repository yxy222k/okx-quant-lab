#!/usr/bin/env python3
"""Reconcile the optimistic paper grid model against real demo-grid fills.

For each market: replay the SAME candle window the live demo grid processed
through the paper grid (intrabar limit-fill) model, using the SAME levels,
and compare both (a) how many fills each books and (b) the equity/realised
each reaches. A large fill gap is the "backtest looks great, live barely
trades" tell; a positive equity gap is the paper model flattering itself in
a ranging market — the regime-dependent optimism that fill counts alone hide.

The replay window is anchored on the grid's persisted deploy_timestamp_ms, so
it survives candle-file trimming. If the deploy candle has been trimmed out of
the file the tool reports "insufficient history" rather than a silently-wrong
ratio. Legacy states without a deploy timestamp fall back to inferring the
deploy candle from the level midpoint (accurate to ~1 candle).
"""
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.candle_store import load_candles_csv
from okx_quant_lab.demo_execution import load_demo_order_ledger
from okx_quant_lab.demo_grid import load_demo_grid_state
from okx_quant_lab.grid_strategy import GridBacktestConfig, run_grid_backtest

BAR = "15m"
MARKETS = ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
ALLOCATION = 100.0
FEE_RATE = 0.001


def reconcile_market(inst_id: str) -> dict | None:
    """Compare paper model vs live demo grid for one market.

    Returns None if the market is not deployed, or a dict with a "status" of
    "ok" (comparison fields populated) or "insufficient_history" (deploy candle
    trimmed off, or nothing processed since deploy yet).
    """
    state_path = ROOT / "data" / "demo" / f"{inst_id}_{BAR}_demo_grid_state.json"
    candle_file = ROOT / "data" / "candles" / f"{inst_id}_{BAR}_demo.csv"
    ledger_file = ROOT / "data" / "orders" / f"demo_grid_orders_{inst_id}.json"

    if not state_path.exists() or not candle_file.exists():
        return None

    state = load_demo_grid_state(state_path)
    candles = load_candles_csv(candle_file)
    if not candles:
        return {"inst_id": inst_id, "status": "insufficient_history"}
    levels = state.levels

    records = load_demo_order_ledger(ledger_file) if ledger_file.exists() else []
    filled = [r for r in records if r.status == "FILLED"]
    demo_buy = sum(1 for r in filled if r.request.side == "BUY")
    demo_sell = sum(1 for r in filled if r.request.side == "SELL")

    window, anchored = _replay_window(candles, state, filled, levels)
    if window is None:
        return {"inst_id": inst_id, "status": "insufficient_history"}

    config = GridBacktestConfig(
        lower_price=levels[0],
        upper_price=levels[-1],
        grid_count=len(state.holdings),
        initial_cash=ALLOCATION,
        fee_rate=FEE_RATE,
        slippage_bps=0.0,
    )
    result = run_grid_backtest(window, config)
    paper_buy = sum(1 for f in result.fills if f.side == "BUY")
    paper_sell = sum(1 for f in result.fills if f.side == "SELL")
    demo_total = demo_buy + demo_sell

    mark = candles[-1].close
    # Value the demo book with the SAME exit-fee haircut the paper model uses
    # in _mark_to_market (cash + asset*mark*(1-fee)), so the equity gap reflects
    # a real strategy difference, not a fee-convention artifact between the two
    # equity functions.
    demo_equity = state.cash + sum(state.holdings) * mark * (1 - FEE_RATE)
    demo_return_pct = (demo_equity / ALLOCATION - 1) * 100

    return {
        "inst_id": inst_id,
        "status": "ok",
        "anchored": anchored,  # True = deploy timestamp; False = midpoint estimate
        "paper_buy": paper_buy,
        "paper_sell": paper_sell,
        "demo_buy": demo_buy,
        "demo_sell": demo_sell,
        "flatter": (paper_buy + paper_sell) / demo_total if demo_total else None,
        # Equity/realised: positive gap = paper model flatters itself vs live.
        "paper_realized": result.realized_profit,
        "demo_realized": state.realized_profit,
        "paper_return_pct": result.return_pct,
        "demo_return_pct": demo_return_pct,
        "equity_gap_pct": result.return_pct - demo_return_pct,
    }


def _replay_window(candles, state, filled, levels):
    """Return (window, anchored) — the candle slice to replay, and whether it
    was anchored on the persisted deploy timestamp. window is None when the
    deploy candle has been trimmed out of the file (can't reconcile reliably).
    """
    deploy_ts = getattr(state, "deploy_timestamp_ms", 0)
    if deploy_ts > 0:
        # The deploy candle must still be reachable, or the replay would
        # cold-start mid-stream and corrupt the counts.
        if candles[0].timestamp_ms > deploy_ts:
            return None, True
        # Live skipped the deploy candle (fast-forwarded last_timestamp_ms), so
        # the paper replay starts strictly after it too. `or None` turns the
        # freshly-deployed case (no candle newer than deploy yet) into the
        # insufficient-history path instead of an empty replay.
        window = [c for c in candles if c.timestamp_ms > deploy_ts]
        return (window or None), True

    # Legacy state (no deploy timestamp): infer the deploy candle as the close
    # nearest the level midpoint, at or before the first real fill.
    ref = (levels[0] + levels[-1]) / 2
    first_fill_ts = min((r.request.created_at_ms for r in filled), default=None)
    pre = [c for c in candles if first_fill_ts is None or c.timestamp_ms <= first_fill_ts]
    deploy = min(pre or candles, key=lambda c: abs(c.close - ref))
    return [c for c in candles if c.timestamp_ms >= deploy.timestamp_ms], False


def main() -> int:
    print("OKX grid reconciliation: paper (optimistic limit) vs demo (real fills)")
    print(f"{'market':<9} {'p_buy':>5} {'p_sell':>6} {'d_buy':>5} {'d_sell':>6} "
          f"{'flatter':>7} | {'paper%':>7} {'demo%':>7} {'eq_gap':>7}")

    for inst_id in MARKETS:
        try:
            row = reconcile_market(inst_id)
        except ValueError as error:
            print(f"{inst_id:<9} replay failed: {error}")
            continue
        if row is None:
            print(f"{inst_id:<9} (not deployed)")
            continue
        if row["status"] != "ok":
            print(f"{inst_id:<9} {row['status']}")
            continue
        flatter = f"{row['flatter']:.1f}x" if row["flatter"] is not None else "n/a"
        est = "" if row["anchored"] else " (est)"
        print(f"{inst_id:<9} {row['paper_buy']:>5} {row['paper_sell']:>6} "
              f"{row['demo_buy']:>5} {row['demo_sell']:>6} {flatter:>7} | "
              f"{row['paper_return_pct']:>6.2f}% {row['demo_return_pct']:>6.2f}% "
              f"{row['equity_gap_pct']:>+6.2f}%{est}")

    print()
    print("flatter = paper fills / demo fills (>1 = paper's limit model books more).")
    print("eq_gap = paper_return - demo_return; POSITIVE = paper model flatters")
    print("itself vs close-confirmed live execution (the regime-dependent optimism).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
