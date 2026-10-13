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

from okx_quant_lab.candle_store import load_candles_csv
from okx_quant_lab.demo_execution import load_demo_order_ledger
from okx_quant_lab.demo_grid import in_outage, load_demo_grid_state
from okx_quant_lab.grid_strategy import GridBacktestConfig, run_grid_backtest

BAR = "15m"
MARKETS = ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
ALLOCATION = 100.0
FEE_RATE = 0.001


def reconcile_market(inst_id: str, root: Path) -> dict | None:
    """Compare paper model vs live demo grid for one market.

    `root` is the project root holding data/demo, data/candles, data/orders.
    Returns None if the market is not deployed, or a dict with a "status" of
    "ok" (comparison fields populated) or "insufficient_history" (deploy candle
    trimmed off, or nothing processed since deploy yet).
    """
    state_path = root / "data" / "demo" / f"{inst_id}_{BAR}_demo_grid_state.json"
    candle_file = root / "data" / "candles" / f"{inst_id}_{BAR}_demo.csv"
    ledger_file = root / "data" / "orders" / f"demo_grid_orders_{inst_id}.json"

    if not state_path.exists() or not candle_file.exists():
        return None

    state = load_demo_grid_state(state_path)
    candles = load_candles_csv(candle_file)
    if not candles:
        return {"inst_id": inst_id, "status": "insufficient_history"}
    levels = state.levels

    records = load_demo_order_ledger(ledger_file) if ledger_file.exists() else []
    filled = [r for r in records if r.status == "FILLED"]
    # The ledger spans every deployment, but the paper replay covers only the
    # current one: counting earlier phases' fills on the live side understated
    # the ratio (0.4-0.6x on 2026-09-20, with phase-1 fills still in the file).
    deploy_ts = getattr(state, "deploy_timestamp_ms", 0)
    if deploy_ts > 0:
        filled = [r for r in filled if r.request.created_at_ms > deploy_ts]
    demo_buy = sum(1 for r in filled if r.request.side == "BUY")
    demo_sell = sum(1 for r in filled if r.request.side == "SELL")

    window, anchored = replay_window(candles, state, filled, levels)
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
    # Downtime the live grid fast-forwarded without trading: the paper replay
    # sees those candles (slots re-arm) but may not fill on them either.
    outages = state.outages
    result = run_grid_backtest(
        window, config, no_trade=(lambda ts: in_outage(state, ts)) if outages else None
    )
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
        "outage_days": sum(b - a for a, b in outages) / 86_400_000 if outages else 0.0,
    }


def replay_window(candles, state, filled, levels):
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
