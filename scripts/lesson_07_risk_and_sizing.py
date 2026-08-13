#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from okx_quant_lab.backtest import BacktestConfig, run_sma_backtest
from okx_quant_lab.candle_store import load_candles_csv
from okx_quant_lab.risk import RiskLimits, build_risk_report, compare_position_sizes


def main() -> int:
    candle_path = ROOT / "data" / "candles" / "BTC-USDT_1H_history.csv"
    if not candle_path.exists():
        raise SystemExit(
            f"Missing {candle_path}. Run scripts/lesson_05_collect_history.py first."
        )

    candles = load_candles_csv(candle_path)
    config = BacktestConfig(
        initial_cash=1_000.0,
        fast_window=20,
        slow_window=50,
        fee_rate=0.001,
        slippage_bps=2.0,
        trade_fraction=1.0,
    )
    limits = RiskLimits(
        max_drawdown_pct=-6.0,
        min_trades=4,
        max_exposure_pct=70.0,
    )

    result = run_sma_backtest(candles, config)
    report = build_risk_report(result, limits)
    sizing = compare_position_sizes(
        candles=candles,
        base_config=config,
        trade_fractions=[1.0, 0.75, 0.5, 0.25],
        limits=limits,
    )

    print("OKX Lesson 07: risk report + position sizing")
    print(f"source:               {candle_path}")
    print(f"candles:              {len(candles)}")
    print(f"strategy:             SMA({config.fast_window},{config.slow_window})")
    print(f"fee_rate:             {config.fee_rate:.4%}")
    print(f"slippage_bps:         {config.slippage_bps:.2f}")
    print()
    print("risk report at full allocation:")
    print(f"return:               {report.return_pct:.2f}%")
    print(f"max_drawdown:         {report.max_drawdown_pct:.2f}%")
    print(f"return_over_drawdown: {report.return_over_drawdown:.2f}")
    print(f"exposure:             {report.exposure_pct:.1f}%")
    print(f"trades:               {report.trades}")
    print(f"passed_limits:        {report.passed}")
    if report.notes:
        print("notes:")
        for note in report.notes:
            print(f"- {note}")

    print()
    print("position size comparison:")
    print("fraction final_equity return% drawdown% exposure% trades pass")
    for row in sizing:
        print(
            f"{row.trade_fraction:>8.2f} "
            f"{row.final_equity:>12.2f} "
            f"{row.return_pct:>7.2f} "
            f"{row.max_drawdown_pct:>9.2f} "
            f"{row.exposure_pct:>9.1f} "
            f"{row.trades:>6} "
            f"{str(row.passed):>4}"
        )

    print()
    print("Lesson: smaller size does not create edge; it buys survival while we keep searching.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
