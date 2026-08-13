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
from okx_quant_lab.monitoring import (
    build_paper_status,
    check_candle_freshness,
    check_paper_state_caught_up,
    render_markdown_report,
)
from okx_quant_lab.paper import PaperConfig, load_paper_state


def main() -> int:
    inst_ids = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT"]
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    checks = []

    for inst_id in inst_ids:
        path = ROOT / "data" / "candles" / f"{inst_id}_1H_scan.csv"
        if path.exists():
            candles = load_candles_csv(path)
        else:
            candles = []
        checks.append(check_candle_freshness(inst_id, candles, now_ms, max_age_hours=36))

    paper_inst_id = "SOL-USDT"
    paper_candles = load_candles_csv(ROOT / "data" / "candles" / "SOL-USDT_1H_scan.csv")
    paper_state = load_paper_state(ROOT / "data" / "paper" / "SOL-USDT_1H_state.json")
    paper_config = PaperConfig(inst_id=paper_inst_id)

    checks.append(check_paper_state_caught_up(paper_state, paper_candles))
    paper_status = build_paper_status(
        inst_id=paper_inst_id,
        state=paper_state,
        candles=paper_candles,
        config=paper_config,
    )

    report = render_markdown_report(
        title="OKX Quant Lab Monitoring Report",
        generated_at_ms=now_ms,
        checks=checks,
        paper_status=paper_status,
    )
    report_path = ROOT / "reports" / "lesson_10_monitoring_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    print("OKX Lesson 10: monitoring report")
    print(f"report:       {report_path}")
    print(f"checks:       {len(checks)}")
    print(f"passed:       {sum(1 for check in checks if check.passed)}")
    print(f"failed:       {sum(1 for check in checks if not check.passed)}")
    print(f"paper_equity: {paper_status.equity:.2f} USDT")
    print()
    for check in checks:
        status = "PASS" if check.passed else "FAIL"
        print(f"{status:<4} {check.name}: {check.message}")

    print()
    print("Lesson: monitoring turns silent drift into visible information.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
