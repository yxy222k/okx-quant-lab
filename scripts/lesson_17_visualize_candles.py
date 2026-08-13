#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.candle_visualization import (
    SAFETY_STATUS,
    candle_data_summary,
    render_candle_dashboard,
)


def main() -> int:
    data_path = ROOT / "freqtrade_lab" / "user_data" / "candle_visualization" / "candles.json"
    html_path = ROOT / "reports" / "candle_visualization.html"

    if not data_path.exists():
        raise FileNotFoundError(
            f"missing candle JSON: {data_path}. "
            "Run the Freqtrade candle exporter first."
        )

    data = json.loads(data_path.read_text(encoding="utf-8"))
    generated_at_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(
        render_candle_dashboard(data, generated_at_ms),
        encoding="utf-8",
    )

    print("OKX Lesson 17: local candle visualization")
    print(f"safety:       {SAFETY_STATUS}")
    print(f"data:         {data_path}")
    print(f"dashboard:    {html_path}")
    print()
    print("pairs:")
    for row in candle_data_summary(data):
        print(
            f"- {row['pair']}: {row['candles']} candles, "
            f"{row['first_time_utc']} -> {row['last_time_utc']}, "
            f"return={row['return_pct']:.2f}%"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
