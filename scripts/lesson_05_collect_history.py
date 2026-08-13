#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.candle_store import save_candles_csv
from okx_quant_lab.okx_public import fetch_historical_candles


def main() -> int:
    inst_id = "BTC-USDT"
    bar = "1H"
    target_count = 1_000
    output_path = ROOT / "data" / "candles" / f"{inst_id}_{bar}_history.csv"

    candles = fetch_historical_candles(inst_id, bar=bar, target_count=target_count)
    save_candles_csv(output_path, candles)

    print("OKX Lesson 05: deeper historical candle collection")
    print(f"instrument:     {inst_id}")
    print(f"bar:            {bar}")
    print(f"requested:      {target_count}")
    print(f"saved_candles:  {len(candles)}")
    print(f"saved_to:       {output_path}")
    print(f"range_utc:      {_seen_at(candles[0].timestamp_ms)} -> {_seen_at(candles[-1].timestamp_ms)}")
    print()
    print("Lesson: deeper data is the fuel for better out-of-sample tests, not a guarantee of edge.")
    return 0


def _seen_at(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
