#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.candle_store import load_candles_csv
from okx_quant_lab.dry_run import (
    DryRunLimits,
    DryRunOrderManager,
    build_sma_order_request,
    load_order_ledger,
    save_order_ledger,
    sma_signal,
)
from okx_quant_lab.paper import PaperConfig, load_paper_state, new_paper_state


SAFETY_STATUS = "public data only, no API keys, no orders submitted."


def main() -> int:
    inst_id = "SOL-USDT"
    bar = "1H"
    candle_path = ROOT / "data" / "candles" / f"{inst_id}_{bar}_demo.csv"
    state_path = ROOT / "data" / "paper" / f"demo_{inst_id}_{bar}_state.json"
    ledger_path = ROOT / "data" / "orders" / f"dry_run_{inst_id}_{bar}_orders.json"
    report_path = ROOT / "reports" / "lesson_15_demo_readiness.md"

    if not candle_path.exists():
        raise SystemExit(f"Missing {candle_path}. Run scripts/safe_demo.py first.")

    candles = load_candles_csv(candle_path)
    config = PaperConfig(inst_id=inst_id)
    state = load_paper_state(state_path) if state_path.exists() else new_paper_state(config)
    limits = DryRunLimits(max_order_usdt=25.0)
    manager = DryRunOrderManager(load_order_ledger(ledger_path) if ledger_path.exists() else [])

    signal = sma_signal(candles, config)
    request = build_sma_order_request(candles, state, config)
    order = manager.submit(request, limits) if request is not None else None
    save_order_ledger(ledger_path, manager.orders)

    report = _render_report(
        inst_id=inst_id,
        bar=bar,
        candles=candles,
        state_path=state_path,
        ledger_path=ledger_path,
        signal=signal,
        request=request,
        order=order,
        order_count=len(manager.orders),
        limits=limits,
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    print("OKX Lesson 15: demo-trading readiness dry run")
    print(f"safety:       {SAFETY_STATUS}")
    print(f"instrument:   {inst_id}")
    print(f"candles:      {len(candles)}")
    print(f"latest_utc:   {_seen_at(candles[-1].timestamp_ms)}")
    print(f"signal:       {signal}")
    print(f"order_status: {_order_status(order)}")
    print(f"order_ledger: {ledger_path}")
    print(f"report:       {report_path}")
    print()
    print("Readiness: NO-GO for live trading. This is still a local dry-run gate.")
    return 0


def _render_report(
    inst_id: str,
    bar: str,
    candles,
    state_path: Path,
    ledger_path: Path,
    signal: str,
    request,
    order,
    order_count: int,
    limits: DryRunLimits,
) -> str:
    lines = [
        "# OKX Demo-Trading Readiness Dry Run",
        "",
        f"Generated at UTC: {_seen_at(int(datetime.now(timezone.utc).timestamp() * 1000))}",
        "",
        f"Safety status: **{SAFETY_STATUS}**",
        "",
        "## Scope",
        "",
        "This is a local dry-run readiness check. It does not use OKX credentials and it does not submit orders.",
        "",
        "## Inputs",
        "",
        f"- Instrument: `{inst_id}`",
        f"- Bar: `{bar}`",
        f"- Candles: `{len(candles)}`",
        f"- Latest candle UTC: `{_seen_at(candles[-1].timestamp_ms)}`",
        f"- Paper state: `{state_path}`",
        f"- Dry-run order ledger: `{ledger_path}`",
        f"- Max dry-run order cap: `{limits.max_order_usdt:.2f}` USDT",
        "",
        "## Current Signal",
        "",
        f"- SMA signal: `{signal}`",
    ]

    if request is None:
        lines.extend(
            [
                "- Order intent: `NONE`",
                "- Reason: current paper state already matches the signal.",
            ]
        )
    else:
        lines.extend(
            [
                f"- Order intent: `{request.side}`",
                f"- Client order id: `{request.client_order_id}`",
                f"- Reference price: `{request.reference_price:.4f}`",
                f"- Quote amount: `{request.quote_amount_usdt:.2f}` USDT",
                f"- Base quantity: `{request.base_quantity:.8f}`",
                f"- Reason: `{request.reason}`",
            ]
        )

    lines.extend(
        [
            "",
            "## Dry-Run Order Gate",
            "",
            f"- Order status: `{_order_status(order)}`",
            f"- Order message: `{order.message if order else 'no order needed'}`",
            f"- Ledger entries: `{order_count}`",
            "",
            "## Live Trading Readiness",
            "",
            "Status: **NO-GO**",
            "",
            "Why:",
            "",
            "- This system still has no authenticated OKX demo API integration.",
            "- It has not reconciled real exchange balances, orders, or fills.",
            "- It has not completed weeks of daily paper monitoring.",
            "- It has not proven duplicate-order prevention against a real API.",
            "- It has not tested partial fills, rejected orders, rate limits, or exchange downtime.",
            "",
            "## Next Required Work",
            "",
            "- Keep this dry-run ledger running daily.",
            "- Add explicit fake partial-fill and rejection simulations.",
            "- Add account reconciliation logic before connecting any OKX demo credentials.",
            "- Add a manual kill switch and alerting.",
            "- Only after that, consider read-only OKX account checks, then OKX demo trading.",
            "",
        ]
    )
    return "\n".join(lines)


def _order_status(order) -> str:
    return order.status if order is not None else "NO_ORDER"


def _seen_at(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
