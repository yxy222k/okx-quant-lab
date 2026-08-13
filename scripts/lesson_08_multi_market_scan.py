#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.backtest import BacktestConfig
from okx_quant_lab.candle_store import load_candles_csv, save_candles_csv
from okx_quant_lab.okx_public import fetch_historical_candles
from okx_quant_lab.risk import RiskLimits
from okx_quant_lab.scanner import scan_symbols


def main() -> int:
    inst_ids = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT"]
    bar = "1H"
    target_count = 500
    candle_map = {}

    print("OKX Lesson 08: multi-market public-data scan")
    print(f"markets:       {', '.join(inst_ids)}")
    print(f"bar:           {bar}")
    print(f"target_count:  {target_count}")
    print()

    for inst_id in inst_ids:
        path = ROOT / "data" / "candles" / f"{inst_id}_{bar}_scan.csv"
        candles = _load_or_fetch(inst_id, bar, target_count, path)
        candle_map[inst_id] = candles
        print(f"ready {inst_id:<9} {len(candles):>4} candles -> {path}")

    config = BacktestConfig(
        initial_cash=1_000.0,
        fast_window=20,
        slow_window=50,
        fee_rate=0.001,
        slippage_bps=2.0,
        trade_fraction=0.5,
    )
    limits = RiskLimits(
        max_drawdown_pct=-8.0,
        min_trades=4,
        max_exposure_pct=80.0,
    )
    rows = scan_symbols(candle_map, config, limits)

    print()
    print(f"strategy:      SMA({config.fast_window},{config.slow_window}), {config.trade_fraction:.0%} allocation")
    print("symbol    return% buyhold% drawdown% exposure% trades pass")
    for row in rows:
        print(
            f"{row.inst_id:<9} "
            f"{row.return_pct:>7.2f} "
            f"{row.buy_hold_return_pct:>8.2f} "
            f"{row.max_drawdown_pct:>9.2f} "
            f"{row.exposure_pct:>9.1f} "
            f"{row.trades:>6} "
            f"{str(row.passed):>4}"
        )

    print()
    print("Lesson: a signal that only looks good on one market is usually a hypothesis, not an edge.")
    return 0


def _load_or_fetch(inst_id: str, bar: str, target_count: int, path: Path):
    if path.exists():
        candles = load_candles_csv(path)
        if len(candles) >= target_count:
            return candles[-target_count:]

    candles = fetch_historical_candles(inst_id, bar=bar, target_count=target_count)
    save_candles_csv(path, candles)
    return candles


if __name__ == "__main__":
    raise SystemExit(main())
