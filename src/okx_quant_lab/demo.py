from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape

from okx_quant_lab.backtest import BacktestConfig, BacktestResult, run_sma_backtest
from okx_quant_lab.grid_strategy import (
    GridBacktestConfig,
    GridBacktestResult,
    run_grid_backtest,
)
from okx_quant_lab.okx_public import Candle
from okx_quant_lab.paper import PaperConfig, PaperState, paper_equity
from okx_quant_lab.safety import ExecutionIntent, SafetyDecision, evaluate_execution_safety


SAFETY_STATUS = "public data only, no API keys, no orders submitted."


@dataclass(frozen=True)
class DemoSummary:
    inst_id: str
    bar: str
    candle_count: int
    first_timestamp_ms: int
    latest_timestamp_ms: int
    fee_rate: float
    slippage_bps: float
    initial_cash: float
    final_equity: float
    return_pct: float
    buy_hold_return_pct: float
    max_drawdown_pct: float
    trades: int
    total_fees: float
    paper_cash: float
    paper_asset: float
    paper_equity: float
    paper_fills: int
    new_paper_fills: int
    safety_allowed: bool


@dataclass(frozen=True)
class DemoReport:
    summary: DemoSummary
    backtest: BacktestResult
    safety: SafetyDecision
    grid: GridBacktestResult | None = None


def build_safe_demo_report(
    inst_id: str,
    bar: str,
    candles: list[Candle],
    paper_state_before: PaperState,
    paper_state_after: PaperState,
    backtest_config: BacktestConfig,
    paper_config: PaperConfig,
    grid_config: GridBacktestConfig | None = None,
) -> DemoReport:
    if not candles:
        raise ValueError("candles must not be empty")

    sorted_candles = sorted(candles, key=lambda candle: candle.timestamp_ms)
    backtest = run_sma_backtest(sorted_candles, backtest_config)
    grid = run_grid_backtest(sorted_candles, grid_config) if grid_config else None
    safety = evaluate_execution_safety(
        ExecutionIntent(
            mode="paper",
            wants_to_submit_order=False,
            has_api_credentials=False,
            user_confirmed_order=False,
            max_order_usdt=0,
        )
    )
    latest_close = sorted_candles[-1].close
    summary = DemoSummary(
        inst_id=inst_id,
        bar=bar,
        candle_count=len(sorted_candles),
        first_timestamp_ms=sorted_candles[0].timestamp_ms,
        latest_timestamp_ms=sorted_candles[-1].timestamp_ms,
        fee_rate=backtest_config.fee_rate,
        slippage_bps=backtest_config.slippage_bps,
        initial_cash=backtest_config.initial_cash,
        final_equity=backtest.final_equity,
        return_pct=backtest.return_pct,
        buy_hold_return_pct=backtest.buy_and_hold_return_pct,
        max_drawdown_pct=backtest.max_drawdown_pct,
        trades=len(backtest.trades),
        total_fees=sum(trade.fee for trade in backtest.trades),
        paper_cash=paper_state_after.cash,
        paper_asset=paper_state_after.asset,
        paper_equity=paper_equity(paper_state_after, latest_close, paper_config),
        paper_fills=len(paper_state_after.fills),
        new_paper_fills=len(paper_state_after.fills) - len(paper_state_before.fills),
        safety_allowed=safety.allowed,
    )

    return DemoReport(summary=summary, backtest=backtest, safety=safety, grid=grid)


def render_demo_markdown(report: DemoReport, generated_at_ms: int) -> str:
    summary = report.summary
    lines = [
        "# OKX Quant Lab Safe Demo",
        "",
        f"Generated at UTC: {_seen_at(generated_at_ms)}",
        "",
        f"Safety status: **{SAFETY_STATUS}**",
        "",
        "## Market Data",
        "",
        f"- Instrument: `{summary.inst_id}`",
        f"- Bar: `{summary.bar}`",
        f"- Candles: `{summary.candle_count}`",
        f"- Range UTC: `{_seen_at(summary.first_timestamp_ms)}` -> `{_seen_at(summary.latest_timestamp_ms)}`",
        "",
        "## Strategy Backtest",
        "",
        f"- Strategy: `SMA({report.backtest.config.fast_window},{report.backtest.config.slow_window})`",
        f"- Initial cash: `{summary.initial_cash:.2f}` USDT",
        f"- Final equity: `{summary.final_equity:.2f}` USDT",
        f"- Return: `{summary.return_pct:.2f}%`",
        f"- Buy and hold return: `{summary.buy_hold_return_pct:.2f}%`",
        f"- Max drawdown: `{summary.max_drawdown_pct:.2f}%`",
        f"- Trades: `{summary.trades}`",
        f"- Total simulated fees: `{summary.total_fees:.4f}` USDT",
        f"- Fee rate: `{summary.fee_rate:.4%}`",
        f"- Slippage: `{summary.slippage_bps:.2f}` bps per fill",
    ]

    if report.grid is not None:
        grid = report.grid
        lines.extend(
            [
                "",
                "## Grid Strategy Backtest",
                "",
                f"- Strategy: `grid({grid.config.lower_price:.4f}..{grid.config.upper_price:.4f}, {grid.config.grid_count} slots)`",
                f"- Return: `{grid.return_pct:.2f}%`",
                f"- Max drawdown: `{grid.max_drawdown_pct:.2f}%`",
                f"- Round trips: `{grid.round_trips}`",
                f"- Realized profit: `{grid.realized_profit:.2f}` USDT",
                f"- Unrealized inventory PnL: `{grid.unrealized_pnl:.2f}` USDT",
                f"- Open slots: `{grid.open_slots}` of `{grid.config.grid_count}`",
            ]
        )

    lines.extend([
        "",
        "## Local Paper State",
        "",
        f"- Cash: `{summary.paper_cash:.2f}` USDT",
        f"- Asset: `{summary.paper_asset:.8f}`",
        f"- Marked equity: `{summary.paper_equity:.2f}` USDT",
        f"- Total fills: `{summary.paper_fills}`",
        f"- New fills this run: `{summary.new_paper_fills}`",
        "",
        "## Safety Checks",
        "",
        "| Check | Status | Detail |",
        "| --- | --- | --- |",
    ])

    for check in report.safety.checks:
        status = "PASS" if check.passed else "FAIL"
        lines.append(f"| {check.name} | {status} | {check.message} |")

    lines.extend(
        [
            "",
            "## Last Backtest Trades",
            "",
            "| Time UTC | Side | Fill | Quantity | Fee |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    for trade in report.backtest.trades[-8:]:
        lines.append(
            f"| {_seen_at(trade.timestamp_ms)} | {trade.side} | "
            f"{trade.price:.4f} | {trade.quantity:.8f} | {trade.fee:.4f} |"
        )
    if not report.backtest.trades:
        lines.append("| n/a | n/a | 0.0000 | 0.00000000 | 0.0000 |")

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "This demo proves the local research loop is wired together. It does not prove the strategy has durable edge.",
            "",
        ]
    )
    return "\n".join(lines)


def render_demo_html(report: DemoReport, generated_at_ms: int) -> str:
    summary = report.summary
    safety_status = "PASS" if report.safety.allowed else "FAIL"
    trade_rows = "\n".join(
        "<tr>"
        f"<td>{escape(_seen_at(trade.timestamp_ms))}</td>"
        f"<td>{escape(trade.side)}</td>"
        f"<td>{trade.price:.4f}</td>"
        f"<td>{trade.quantity:.8f}</td>"
        f"<td>{trade.fee:.4f}</td>"
        "</tr>"
        for trade in report.backtest.trades[-8:]
    )
    if not trade_rows:
        trade_rows = "<tr><td>n/a</td><td>n/a</td><td>0.0000</td><td>0.00000000</td><td>0.0000</td></tr>"

    safety_rows = "\n".join(
        "<tr>"
        f"<td>{escape(check.name)}</td>"
        f"<td>{'PASS' if check.passed else 'FAIL'}</td>"
        f"<td>{escape(check.message)}</td>"
        "</tr>"
        for check in report.safety.checks
    )

    grid_section = ""
    if report.grid is not None:
        grid = report.grid
        grid_section = f"""
    <section>
      <h2>Grid Strategy Backtest</h2>
      <table>
        <tbody>
          <tr><th>Range</th><td>{grid.config.lower_price:.4f} .. {grid.config.upper_price:.4f} ({grid.config.grid_count} slots)</td></tr>
          <tr><th>Return</th><td>{grid.return_pct:.2f}%</td></tr>
          <tr><th>Max drawdown</th><td>{grid.max_drawdown_pct:.2f}%</td></tr>
          <tr><th>Round trips</th><td>{grid.round_trips}</td></tr>
          <tr><th>Realized profit</th><td>{grid.realized_profit:.2f} USDT</td></tr>
          <tr><th>Unrealized inventory PnL</th><td>{grid.unrealized_pnl:.2f} USDT</td></tr>
          <tr><th>Open slots</th><td>{grid.open_slots} of {grid.config.grid_count}</td></tr>
        </tbody>
      </table>
    </section>"""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OKX Quant Lab Safe Demo</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #14171a;
      --muted: #5f6b7a;
      --line: #d9dee7;
      --good: #0f7b55;
      --warn: #9a5b00;
      --accent: #125d98;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
    }}
    header {{
      background: #111820;
      color: #fff;
      padding: 28px 32px;
      border-bottom: 4px solid var(--accent);
    }}
    header h1 {{
      margin: 0 0 8px;
      font-size: 28px;
      font-weight: 700;
    }}
    header p {{
      margin: 0;
      color: #d7dee8;
      font-size: 15px;
    }}
    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 24px;
    }}
    .status {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 16px 18px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      margin-bottom: 18px;
    }}
    .badge {{
      display: inline-block;
      padding: 4px 9px;
      border-radius: 999px;
      background: #e8f5ef;
      color: var(--good);
      font-weight: 700;
      font-size: 13px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }}
    .metric {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      min-height: 94px;
    }}
    .metric span {{
      display: block;
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 8px;
    }}
    .metric strong {{
      display: block;
      font-size: 24px;
    }}
    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      margin-bottom: 18px;
    }}
    h2 {{
      margin: 0 0 12px;
      font-size: 18px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    th, td {{
      text-align: left;
      padding: 10px 8px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-weight: 600;
    }}
    .muted {{ color: var(--muted); }}
    @media (max-width: 840px) {{
      header {{ padding: 22px 20px; }}
      main {{ padding: 16px; }}
      .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .status {{ display: block; }}
    }}
    @media (max-width: 520px) {{
      .grid {{ grid-template-columns: 1fr; }}
      table {{ font-size: 13px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>OKX Quant Lab Safe Demo</h1>
    <p>Generated at UTC: {escape(_seen_at(generated_at_ms))}</p>
  </header>
  <main>
    <div class="status">
      <div>
        <strong>Safety status:</strong> {escape(SAFETY_STATUS)}
        <div class="muted">Mode: local paper simulation. Credentials: not used. Orders: not submitted.</div>
      </div>
      <span class="badge">{safety_status}</span>
    </div>
    <div class="grid">
      <div class="metric"><span>Instrument</span><strong>{escape(summary.inst_id)}</strong></div>
      <div class="metric"><span>Final Equity</span><strong>{summary.final_equity:.2f}</strong></div>
      <div class="metric"><span>Return</span><strong>{summary.return_pct:.2f}%</strong></div>
      <div class="metric"><span>Max Drawdown</span><strong>{summary.max_drawdown_pct:.2f}%</strong></div>
      <div class="metric"><span>Trades</span><strong>{summary.trades}</strong></div>
      <div class="metric"><span>Total Fees</span><strong>{summary.total_fees:.4f}</strong></div>
      <div class="metric"><span>Slippage</span><strong>{summary.slippage_bps:.2f} bps</strong></div>
      <div class="metric"><span>Paper Equity</span><strong>{summary.paper_equity:.2f}</strong></div>
    </div>
    <section>
      <h2>Market Data</h2>
      <table>
        <tbody>
          <tr><th>Candles</th><td>{summary.candle_count}</td></tr>
          <tr><th>Range UTC</th><td>{escape(_seen_at(summary.first_timestamp_ms))} -> {escape(_seen_at(summary.latest_timestamp_ms))}</td></tr>
          <tr><th>Bar</th><td>{escape(summary.bar)}</td></tr>
        </tbody>
      </table>
    </section>
    <section>
      <h2>Paper State</h2>
      <table>
        <tbody>
          <tr><th>Cash</th><td>{summary.paper_cash:.2f} USDT</td></tr>
          <tr><th>Asset</th><td>{summary.paper_asset:.8f}</td></tr>
          <tr><th>Total fills</th><td>{summary.paper_fills}</td></tr>
          <tr><th>New fills this run</th><td>{summary.new_paper_fills}</td></tr>
        </tbody>
      </table>
    </section>{grid_section}
    <section>
      <h2>Safety Checks</h2>
      <table>
        <thead><tr><th>Check</th><th>Status</th><th>Detail</th></tr></thead>
        <tbody>{safety_rows}</tbody>
      </table>
    </section>
    <section>
      <h2>Last Backtest Trades</h2>
      <table>
        <thead><tr><th>Time UTC</th><th>Side</th><th>Fill</th><th>Quantity</th><th>Fee</th></tr></thead>
        <tbody>{trade_rows}</tbody>
      </table>
    </section>
  </main>
</body>
</html>
"""


def _seen_at(timestamp_ms: int) -> str:
    if timestamp_ms == 0:
        return "never"
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()
