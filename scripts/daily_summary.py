#!/usr/bin/env python3
"""Daily heartbeat summary: demo grids, paper strategies, account equity.

Always prints (never silent) — schedule it once a day so silence from the
watchdog loops can safely mean "nothing happened".
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.candle_store import load_candles_csv
from okx_quant_lab.demo_execution import load_demo_order_ledger
from okx_quant_lab.demo_grid import (
    demo_grid_equity,
    load_demo_grid_state,
    open_slot_count,
)
from okx_quant_lab.donchian_paper import DonchianPaperConfig, donchian_paper_equity
from okx_quant_lab.grid_paper import GridPaperConfig, grid_paper_equity, load_grid_paper_state
from okx_quant_lab.okx_demo_private import fetch_demo_balance, load_demo_credentials
from okx_quant_lab.okx_public import fetch_ticker
from okx_quant_lab.paper import PaperConfig, load_paper_state, paper_equity


MARKETS = ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
DAY_MS = 24 * 60 * 60 * 1_000


def main() -> int:
    now_ms = int(time.time() * 1000)
    lines = [f"OKX 日报 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"]

    total_equity = 0.0
    total_realized = 0.0
    total_fills_24h = 0
    idle_notes: list[str] = []
    for inst_id in MARKETS:
        state_path = ROOT / "data" / "demo" / f"{inst_id}_15m_demo_grid_state.json"
        ledger_path = ROOT / "data" / "orders" / f"demo_grid_orders_{inst_id}.json"
        if not state_path.exists():
            lines.append(f"{inst_id}: (not deployed)")
            continue
        state = load_demo_grid_state(state_path)
        mark = fetch_ticker(inst_id).last
        equity = demo_grid_equity(state, mark)
        records = load_demo_order_ledger(ledger_path) if ledger_path.exists() else []
        fills_24h = sum(
            1
            for record in records
            if record.status == "FILLED"
            and record.request.created_at_ms >= now_ms - DAY_MS
        )
        total_equity += equity
        total_realized += state.realized_profit
        total_fills_24h += fills_24h
        below = " ⚠️低于区间" if mark < state.levels[0] else ""
        breaker = " ⚠️熔断中" if state.breaker_tripped else ""
        lines.append(
            f"{inst_id.split('-')[0]}: 权益 {equity:.2f}/100 持仓 "
            f"{open_slot_count(state)}/20 已实现 {state.realized_profit:+.2f} "
            f"24h成交 {fills_24h}{below}{breaker}"
        )
        idle = _idle_grid_note(inst_id, state, mark, records, now_ms)
        if idle:
            idle_notes.append(idle)

    lines.append(
        f"网格合计: 权益 {total_equity:.2f}/300 已实现 {total_realized:+.2f} "
        f"24h成交 {total_fills_24h}"
    )
    if idle_notes:
        lines.append("⚠️ 网格闲置(空仓且价格在区间外，不会再成交): " + "; ".join(idle_notes))

    try:
        balance = fetch_demo_balance(load_demo_credentials())
        lines.append(f"模拟盘账户总值: {balance['total_equity_usd']:.0f} USD")
    except Exception as error:
        lines.append(f"模拟盘账户查询失败: {type(error).__name__}")

    lines.append(_paper_line())
    lines.append(_reconcile_line())
    print("\n".join(lines))
    return 0


def _idle_grid_note(
    inst_id: str,
    state,
    mark: float,
    records: list,
    now_ms: int,
) -> str | None:
    """Flag a grid that has stopped participating entirely.

    A long-only grid holding nothing while price sits outside its range can
    never fill: there is no inventory to sell and every buy level is out of
    reach. That is not a risk condition, which is why the hourly watchdog
    stays silent on it (below-range trapped inventory is the one it guards),
    but it does mean the strategy is doing nothing at all — a fact worth
    stating once a day rather than leaving for someone to notice.
    """
    if open_slot_count(state) > 0:
        return None
    lower, upper = state.levels[0], state.levels[-1]
    if lower <= mark <= upper:
        return None

    symbol = inst_id.split("-")[0]
    edge = upper if mark > upper else lower
    move_pct = (edge / mark - 1) * 100
    fills = [r for r in records if r.status == "FILLED"]
    if fills:
        days = (now_ms - max(r.request.created_at_ms for r in fills)) / DAY_MS
        since = f"，最近成交 {days:.1f} 天前"
    else:
        since = "，从未成交"
    return f"{symbol} 需 {move_pct:+.1f}% 回到 {edge:.4f}{since}"


def _reconcile_line() -> str:
    """Compact paper-vs-demo reconciliation: fill-count ratio and equity gap."""
    try:
        from okx_quant_lab.reconcile import MARKETS, reconcile_market

        fills = []
        gaps = []
        worst_flatter = 0.0
        worst_gap = 0.0
        stale = []
        for inst_id in MARKETS:
            row = reconcile_market(inst_id, ROOT)
            if not row:
                continue
            if row.get("status") == "insufficient_history":
                stale.append(inst_id.split("-")[0])
                continue
            if row.get("status") != "ok":
                continue
            sym = inst_id.split("-")[0]
            if row["flatter"] is not None:
                fills.append(f"{sym} {row['flatter']:.1f}x")
                worst_flatter = max(worst_flatter, row["flatter"])
            gaps.append(f"{sym} {row['equity_gap_pct']:+.1f}%")
            worst_gap = max(worst_gap, row["equity_gap_pct"])

        if not fills and not gaps and not stale:
            return "对账: 暂无成交"

        out = []
        if fills:
            flag = " ⚠️成交比偏高" if worst_flatter >= 2.0 else ""
            out.append("成交比 " + ", ".join(fills) + flag)
        if gaps:
            flag = " ⚠️纸面权益偏乐观" if worst_gap >= 1.0 else ""
            out.append("权益差(纸面−实盘) " + ", ".join(gaps) + flag)
        if stale:
            out.append("历史不足: " + ", ".join(stale))
        return "对账: " + " | ".join(out)
    except Exception as error:
        return f"对账: 计算失败 {type(error).__name__}"


def _paper_line() -> str:
    parts = []
    try:
        sol_close = load_candles_csv(
            ROOT / "data" / "candles" / "SOL-USDT_1H_scan.csv"
        )[-1].close
        eth_close = load_candles_csv(
            ROOT / "data" / "candles" / "ETH-USDT_1H_scan.csv"
        )[-1].close

        sma_path = ROOT / "data" / "paper" / "SOL-USDT_1H_state.json"
        if sma_path.exists():
            state = load_paper_state(sma_path)
            parts.append(f"sma {paper_equity(state, sol_close, PaperConfig(inst_id='SOL-USDT')):.0f}")

        grid_path = ROOT / "data" / "paper" / "SOL-USDT_1H_grid_state.json"
        if grid_path.exists():
            state = load_grid_paper_state(grid_path)
            parts.append(
                f"grid {grid_paper_equity(state, sol_close, GridPaperConfig(inst_id='SOL-USDT')):.0f}"
            )

        donchian_path = ROOT / "data" / "paper" / "ETH-USDT_1H_donchian_state.json"
        if donchian_path.exists():
            state = load_paper_state(donchian_path)
            parts.append(
                f"donchian {donchian_paper_equity(state, eth_close, DonchianPaperConfig(inst_id='ETH-USDT')):.0f}"
            )
    except Exception as error:
        return f"纸面策略: 读取失败 {type(error).__name__}"

    return "纸面策略(各1000起步): " + ", ".join(parts)


if __name__ == "__main__":
    raise SystemExit(main())
