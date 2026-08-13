#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.backtest import BacktestConfig
from okx_quant_lab.candle_store import load_candles_csv, merge_candles, save_candles_csv
from okx_quant_lab.demo import (
    SAFETY_STATUS,
    build_safe_demo_report,
    render_demo_html,
    render_demo_markdown,
)
from okx_quant_lab.grid_strategy import grid_config_from_reference
from okx_quant_lab.okx_public import fetch_candles, fetch_historical_candles
from okx_quant_lab.paper import (
    PaperConfig,
    load_paper_state,
    new_paper_state,
    run_paper_session,
    save_paper_state,
)


def main() -> int:
    inst_id = "SOL-USDT"
    bar = "1H"
    candle_path = ROOT / "data" / "candles" / f"{inst_id}_{bar}_demo.csv"
    state_path = ROOT / "data" / "paper" / f"demo_{inst_id}_{bar}_state.json"
    markdown_path = ROOT / "reports" / "safe_demo_report.md"
    html_path = ROOT / "reports" / "safe_demo_dashboard.html"

    existing = load_candles_csv(candle_path) if candle_path.exists() else []
    if len(existing) < 300:
        existing = fetch_historical_candles(inst_id, bar=bar, target_count=500)
    latest = fetch_candles(inst_id, bar=bar, limit=200)
    candles = merge_candles(existing, latest)[-500:]
    save_candles_csv(candle_path, candles)

    paper_config = PaperConfig(
        inst_id=inst_id,
        initial_cash=1_000.0,
        fast_window=20,
        slow_window=50,
        fee_rate=0.001,
        slippage_bps=2.0,
        trade_fraction=0.5,
    )
    backtest_config = BacktestConfig(
        initial_cash=1_000.0,
        fast_window=20,
        slow_window=50,
        fee_rate=0.001,
        slippage_bps=2.0,
        trade_fraction=0.5,
    )

    paper_state_before = (
        load_paper_state(state_path)
        if state_path.exists()
        else new_paper_state(paper_config)
    )
    paper_state_after = run_paper_session(candles, paper_state_before, paper_config)
    save_paper_state(state_path, paper_state_after)

    grid_config = grid_config_from_reference(
        reference_price=candles[0].open,
        range_pct=15.0,
        grid_count=10,
        initial_cash=1_000.0,
        fee_rate=0.001,
    )

    report = build_safe_demo_report(
        inst_id=inst_id,
        bar=bar,
        candles=candles,
        paper_state_before=paper_state_before,
        paper_state_after=paper_state_after,
        backtest_config=backtest_config,
        paper_config=paper_config,
        grid_config=grid_config,
    )
    generated_at_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_demo_markdown(report, generated_at_ms), encoding="utf-8")
    html_path.write_text(render_demo_html(report, generated_at_ms), encoding="utf-8")

    summary = report.summary
    print("OKX Quant Lab Safe Demo")
    print(f"safety:              {SAFETY_STATUS}")
    print(f"instrument:          {summary.inst_id}")
    print(f"bar:                 {summary.bar}")
    print(f"candles:             {summary.candle_count}")
    print(f"range_utc:           {_seen_at(summary.first_timestamp_ms)} -> {_seen_at(summary.latest_timestamp_ms)}")
    print(f"strategy:            SMA({backtest_config.fast_window},{backtest_config.slow_window})")
    print(f"fee_rate:            {summary.fee_rate:.4%}")
    print(f"slippage_bps:        {summary.slippage_bps:.2f}")
    print(f"trades:              {summary.trades}")
    print(f"total_fees:          {summary.total_fees:.4f} USDT")
    print(f"final_equity:        {summary.final_equity:.2f} USDT")
    print(f"return:              {summary.return_pct:.2f}%")
    print(f"buy_hold_return:     {summary.buy_hold_return_pct:.2f}%")
    print(f"max_drawdown:        {summary.max_drawdown_pct:.2f}%")
    print(f"paper_equity:        {summary.paper_equity:.2f} USDT")
    print(f"paper_fills:         {summary.paper_fills}")
    print(f"new_paper_fills:     {summary.new_paper_fills}")
    if report.grid is not None:
        print(
            f"grid:                return={report.grid.return_pct:.2f}% "
            f"realized={report.grid.realized_profit:.2f} "
            f"unrealized={report.grid.unrealized_pnl:.2f} "
            f"open_slots={report.grid.open_slots}"
        )
    print(f"markdown_report:     {markdown_path}")
    print(f"html_dashboard:      {html_path}")
    print()
    print("Demo meaning: the research-to-paper loop works locally; it is not evidence of durable live edge.")
    return 0


def _seen_at(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
