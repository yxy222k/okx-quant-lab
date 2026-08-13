#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.market_math import spread_stats
from okx_quant_lab.okx_public import fetch_ticker


def main() -> int:
    ticker = fetch_ticker("BTC-USDT")
    stats = spread_stats(ticker.bid, ticker.ask)
    seen_at = datetime.fromtimestamp(ticker.timestamp_ms / 1000, tz=timezone.utc)

    print("OKX public market snapshot")
    print(f"instrument:   {ticker.inst_id}")
    print(f"seen_at_utc:  {seen_at.isoformat()}")
    print(f"last:         {ticker.last:.2f}")
    print(f"bid:          {ticker.bid:.2f}")
    print(f"ask:          {ticker.ask:.2f}")
    print(f"spread:       {stats.spread:.4f}")
    print(f"spread_bps:   {stats.spread_bps:.4f}")
    print()
    print("Lesson: a strategy must beat spread + fees + slippage before it has any real edge.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
